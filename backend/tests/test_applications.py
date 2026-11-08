import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes import applications, jobs
from core import database
from core.runs import execute_run
from core.application_lifecycle import TRANSITIONS, history_entry, transition
from models.application import AgentEvent, Application
from models.job import Job
from models.profile import UserProfile


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.engine_patch = patch.object(database, "engine", self.engine)
        self.session_patch = patch.object(database, "AsyncSessionLocal", self.sessions)
        self.engine_patch.start()
        self.session_patch.start()
        self.dispatch_patch = patch("core.runs.dispatch_run", new=AsyncMock())
        self.dispatch_patch.start()
        self.publish_patch = patch("core.websocket.Redis.from_url")
        redis_factory = self.publish_patch.start()
        redis_factory.return_value.__aenter__.return_value.publish = AsyncMock()
        await database.init_db()
        app = FastAPI()
        app.include_router(applications.router)
        app.include_router(jobs.router)
        self.client = AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")
        async with self.sessions() as session:
            job = Job(title="Engineer", company="Example", portal="linkedin", url="https://example.com/job", status="ranked", fit_score=80)
            session.add(job)
            session.add(UserProfile(full_name="Candidate", email="candidate@example.com"))
            await session.commit()
            self.job_id = job.id

    async def asyncTearDown(self):
        await self.client.aclose()
        self.session_patch.stop()
        self.dispatch_patch.stop()
        self.publish_patch.stop()
        self.engine_patch.stop()
        await self.engine.dispose()

    async def save(self):
        response = await self.client.put(f"/api/applications/{self.job_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def move(self, status, expected, **values):
        return await self.client.patch(f"/api/applications/{self.job_id}/status", json={
            "status": status, "expected_status": expected, **values,
        })

    async def test_save_is_idempotent_and_requires_existing_job(self):
        first = await self.save()
        second = await self.save()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "saved")
        self.assertEqual(first["document_status"], "not_started")
        self.assertEqual(len(second["status_history"]), 1)
        self.assertEqual(first["job"]["company"], "Example")
        self.assertEqual((await self.client.put("/api/applications/999999")).status_code, 404)
        self.assertEqual((await self.client.get("/api/applications")).json()["count"], 1)

    async def test_lifecycle_and_timeline_leave_job_processing_state_unchanged(self):
        await self.save()
        previous = "saved"
        for status in ["preparing", "applied", "screening", "interviewing", "offer", "accepted"]:
            response = await self.move(status, previous, note=f"Moving to {status}")
            self.assertEqual(response.status_code, 200, response.text)
            previous = status
        application = response.json()
        self.assertEqual(len(application["status_history"]), 7)
        self.assertEqual(application["status_history"][-1]["note"], "Moving to accepted")
        self.assertIsNotNone(application["applied_at"])
        self.assertEqual(application["allowed_transitions"], [])
        self.assertEqual((await self.move("applied", "accepted")).status_code, 422)
        result = await self.client.get(f"/api/jobs/{self.job_id}")
        self.assertEqual(result.json()["status"], "ranked")

    async def test_invalid_stale_and_repeated_transitions(self):
        await self.save()
        self.assertEqual((await self.move("accepted", "saved")).status_code, 422)
        self.assertEqual((await self.move("anything", "saved")).status_code, 422)
        response = await self.move("applied", "saved")
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.move("screening", "saved")).status_code, 409)
        repeated = await self.move("applied", "applied")
        self.assertEqual(len(repeated.json()["status_history"]), 2)
        self.assertEqual(repeated.json()["applied_at"], response.json()["applied_at"])
        for status in ("rejected", "withdrawn"):
            self.assertEqual(TRANSITIONS[status], ())

    async def test_metadata_interviews_timezone_and_reminders(self):
        await self.save()
        payload = {
            "recruiter_name": "Recruiter", "recruiter_email": "recruiter@example.com",
            "recruiter_phone": "+1 555 0100", "notes": "Referred by colleague",
            "preparation_notes": "Review distributed systems", "outcome": "Awaiting feedback",
            "deadline_at": "2026-11-01T12:00:00+05:30",
            "follow_up_at": "2026-11-02T12:00:00Z",
            "interview_rounds": [{"id": "round-1", "round": 1, "type": "Technical", "date": "2026-11-03T12:00:00+05:30", "notes": "Good discussion", "preparation_notes": "Practice APIs", "outcome": "Passed"}],
        }
        response = await self.client.patch(f"/api/applications/{self.job_id}", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deadline_at"], "2026-11-01T06:30:00")
        self.assertEqual(response.json()["interview_rounds"][0]["date"], "2026-11-03T06:30:00")
        response = await self.client.patch(f"/api/applications/{self.job_id}", json={"follow_up_completed_at": "2026-11-02T13:00:00Z"})
        self.assertIsNotNone(response.json()["follow_up_completed_at"])
        response = await self.client.patch(f"/api/applications/{self.job_id}", json={"follow_up_at": "2026-11-04T12:00:00Z"})
        self.assertIsNone(response.json()["follow_up_completed_at"])
        self.assertEqual(response.json()["notes"], payload["notes"])
        self.assertEqual(response.json()["status"], "saved")
        duplicate = payload["interview_rounds"] * 2
        self.assertEqual((await self.client.patch(f"/api/applications/{self.job_id}", json={"interview_rounds": duplicate})).status_code, 422)
        self.assertEqual((await self.client.patch(f"/api/applications/{self.job_id}", json={"status": "accepted"})).status_code, 422)

    async def test_submitted_application_date_cannot_be_cleared(self):
        await self.save()
        await self.move("applied", "saved")
        response = await self.client.patch(f"/api/applications/{self.job_id}", json={"applied_at": None})
        self.assertEqual(response.status_code, 422)

    async def test_document_success_and_failure_preserve_applied_status_and_history(self):
        await self.save()
        applied = (await self.move("applied", "saved")).json()
        generated = {"one_pager_path": "/tmp/resume.pdf", "one_pager_html": "<p>Resume</p>", "cover_letter_path": "/tmp/letter.pdf", "cover_letter_text": "Letter"}
        with patch("agents.docgen.DocGenAgent.run", new=AsyncMock(return_value=generated)):
            response = await self.client.post(f"/api/applications/{self.job_id}/generate-docs")
            self.assertEqual(response.json()["run"]["status"], "queued")
            await execute_run(response.json()["run_id"])
        self.assertEqual(response.status_code, 202, response.text)
        ready = (await self.client.get(f"/api/applications/{self.job_id}")).json()
        self.assertEqual(ready["status"], "applied")
        self.assertEqual(ready["document_status"], "ready")
        self.assertEqual(ready["status_history"], applied["status_history"])
        with patch("agents.docgen.DocGenAgent.run", new=AsyncMock(side_effect=RuntimeError("Model unavailable"))):
            queued = await self.client.post(f"/api/applications/{self.job_id}/generate-docs")
            await execute_run(queued.json()["run_id"])
        failed = (await self.client.get(f"/api/applications/{self.job_id}")).json()
        self.assertEqual(failed["status"], "applied")
        self.assertEqual(failed["document_status"], "failed")
        self.assertEqual(failed["document_error"], "Model unavailable")
        self.assertEqual(failed["one_pager_path"], ready["one_pager_path"])

    async def test_duplicate_document_requests_share_the_existing_run(self):
        with patch.object(applications, "_run_docgen", new=AsyncMock()):
            first = await self.client.post(f"/api/applications/{self.job_id}/generate-docs")
            second = await self.client.post(f"/api/applications/{self.job_id}/generate-docs")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["run_id"], second.json()["run_id"])
        self.assertTrue(second.json()["duplicate"])
        application = (await self.client.get(f"/api/applications/{self.job_id}")).json()
        self.assertEqual(application["status"], "preparing")
        self.assertEqual(application["document_status"], "generating")

    async def test_tracked_jobs_survive_cleanup_and_clear(self):
        from agents.pipeline import _cleanup_stale_jobs
        await self.save()
        old = datetime.utcnow() - timedelta(days=60)
        async with self.sessions() as session:
            job = await session.get(Job, self.job_id)
            job.posted_at = old
            session.add(Job(title="Old", company="Other", portal="linkedin", url="https://example.com/old", posted_at=old))
            await session.commit()
            self.assertEqual(await _cleanup_stale_jobs(session, 7), 1)
            await session.commit()
        response = await self.client.delete("/api/jobs/clear")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted"], 0)
        self.assertEqual((await self.client.get(f"/api/jobs/{self.job_id}")).status_code, 200)

    async def test_job_filters_use_application_lifecycle(self):
        await self.save()
        await self.move("applied", "saved")
        applied = await self.client.get("/api/jobs?application_status=applied")
        self.assertEqual(applied.json()["count"], 1)
        saved = await self.client.get("/api/jobs?application_status=saved")
        self.assertEqual(saved.json()["count"], 0)

    async def test_delete_removes_application_job_and_events_but_preserves_other_records(self):
        await self.save()
        await self.move("applied", "saved")
        await self.move("offer", "applied")
        await self.move("accepted", "offer")
        async with self.sessions() as session:
            session.add(AgentEvent(agent="docgen", status="done", message="Generated documents", job_id=self.job_id))
            session.add(AgentEvent(agent="search", status="done", message="Search complete"))
            other = Job(title="Other", company="Other", portal="linkedin", url="https://example.com/other")
            session.add(other)
            await session.flush()
            session.add(Application(job_id=other.id, status="saved"))
            await session.commit()
            other_id = other.id
        response = await self.client.delete(f"/api/applications/{self.job_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["cleanup_warning"])
        self.assertEqual((await self.client.get(f"/api/applications/{self.job_id}")).status_code, 404)
        self.assertEqual((await self.client.get(f"/api/jobs/{self.job_id}")).status_code, 404)
        self.assertEqual((await self.client.get("/api/applications")).json()["count"], 1)
        async with self.sessions() as session:
            events = (await session.execute(select(AgentEvent))).scalars().all()
            self.assertEqual(len(events), 1)
            self.assertIsNone(events[0].job_id)
            self.assertIsNotNone(await session.get(Job, other_id))
            self.assertIsNotNone((await session.execute(select(UserProfile))).scalar_one_or_none())

    async def test_delete_missing_application_does_not_remove_untracked_job(self):
        self.assertEqual((await self.client.delete("/api/applications/999999")).status_code, 404)
        self.assertEqual((await self.client.delete(f"/api/applications/{self.job_id}")).status_code, 404)
        self.assertEqual((await self.client.get(f"/api/jobs/{self.job_id}")).status_code, 200)

    async def test_delete_waits_for_document_generation(self):
        await self.save()
        async with self.sessions() as session:
            application = (await session.execute(select(Application))).scalar_one()
            application.document_status = "generating"
            await session.commit()
        response = await self.client.delete(f"/api/applications/{self.job_id}")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((await self.client.get(f"/api/applications/{self.job_id}")).status_code, 200)
        self.assertEqual((await self.client.get(f"/api/jobs/{self.job_id}")).status_code, 200)

    async def test_delete_removes_generated_pdf_and_html_files(self):
        await self.save()
        with TemporaryDirectory() as directory:
            documents = Path(directory)
            files = [documents / name for name in ("resume.pdf", "resume.html", "letter.pdf", "letter.html")]
            for path in files:
                path.write_text("test document")
            async with self.sessions() as session:
                application = (await session.execute(select(Application))).scalar_one()
                application.one_pager_path = str(documents / "resume.pdf")
                application.cover_letter_path = str(documents / "letter.html")
                await session.commit()
            with patch.object(applications.settings, "documents_dir", directory):
                response = await self.client.delete(f"/api/applications/{self.job_id}")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(all(not path.exists() for path in files))

    async def test_delete_preserves_shared_documents_and_files_outside_documents_directory(self):
        await self.save()
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside_directory:
            shared_pdf = Path(directory) / "shared.pdf"
            shared_html = shared_pdf.with_suffix(".html")
            outside_file = Path(outside_directory) / "private.pdf"
            for path in (shared_pdf, shared_html, outside_file):
                path.write_text("keep this file")
            async with self.sessions() as session:
                application = (await session.execute(select(Application))).scalar_one()
                application.one_pager_path = str(shared_pdf)
                application.cover_letter_path = str(outside_file)
                other = Job(title="Other", company="Other", portal="linkedin", url="https://example.com/shared")
                session.add(other)
                await session.flush()
                session.add(Application(job_id=other.id, one_pager_path=str(shared_html)))
                await session.commit()
            with patch.object(applications.settings, "documents_dir", directory):
                response = await self.client.delete(f"/api/applications/{self.job_id}")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(all(path.exists() for path in (shared_pdf, shared_html, outside_file)))

    async def test_delete_reports_file_cleanup_errors_without_restoring_application(self):
        await self.save()
        with TemporaryDirectory() as directory:
            async with self.sessions() as session:
                application = (await session.execute(select(Application))).scalar_one()
                application.one_pager_path = str(Path(directory) / "resume.pdf")
                await session.commit()
            with patch.object(applications.settings, "documents_dir", directory), patch.object(Path, "unlink", side_effect=PermissionError("File is locked")):
                response = await self.client.delete(f"/api/applications/{self.job_id}")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIsNotNone(response.json()["cleanup_warning"])
            self.assertEqual((await self.client.get(f"/api/jobs/{self.job_id}")).status_code, 404)

    async def test_all_transition_rules(self):
        for previous, allowed in TRANSITIONS.items():
            for target in TRANSITIONS:
                record = Application(status=previous, status_history=[history_entry(None, previous)])
                if target == previous or target in allowed:
                    transition(record, target)
                    self.assertEqual(record.status, target)
                else:
                    with self.assertRaises(ValueError):
                        transition(record, target)


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_migration_preserves_documents_and_job_tracking_and_is_repeatable(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(database.Base.metadata.create_all)
                await connection.execute(Job.__table__.insert(), [
                    {"id": 1, "title": "Engineer", "company": "Example", "url": "https://example.com/1", "portal": "linkedin", "status": "applied"},
                    {"id": 2, "title": "Engineer", "company": "Other", "url": "https://example.com/2", "portal": "linkedin", "status": "saved"},
                    {"id": 3, "title": "Engineer", "company": "Third", "url": "https://example.com/3", "portal": "linkedin", "status": "ranked"},
                ])
                await connection.execute(Application.__table__.insert(), [
                    {"job_id": 1, "status": "ready", "one_pager_path": "resume.pdf", "apply_notes": "Existing application notes", "rejection_reason": None},
                    {"job_id": 3, "status": "applied", "one_pager_path": "submitted.pdf", "apply_notes": None, "rejection_reason": "Existing feedback"},
                ])
                for column in ["document_status", "document_error", "recruiter_name", "recruiter_email", "recruiter_phone", "notes", "preparation_notes", "outcome", "deadline_at", "follow_up_at", "follow_up_completed_at", "status_history"]:
                    await connection.execute(text(f"ALTER TABLE applications DROP COLUMN {column}"))
            with patch.object(database, "engine", engine):
                await database.init_db()
                await database.init_db()
            async with async_sessionmaker(engine)() as session:
                rows = (await session.execute(select(Application))).scalars().all()
                by_job = {entry.job_id: entry for entry in rows}
                self.assertEqual(len(rows), 3)
                self.assertEqual(by_job[1].status, "applied")
                self.assertEqual(by_job[1].document_status, "ready")
                self.assertEqual(by_job[1].one_pager_path, "resume.pdf")
                self.assertEqual(by_job[3].document_status, "ready")
                self.assertEqual(by_job[1].notes, "Existing application notes")
                self.assertEqual(by_job[3].outcome, "Existing feedback")
                self.assertEqual(by_job[2].status, "saved")
                self.assertEqual(len(by_job[1].status_history), 2)
                self.assertEqual((await session.get(Job, 1)).status, "new")
        finally:
            await engine.dispose()

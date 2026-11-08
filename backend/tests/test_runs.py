import asyncio
import json
import os
import unittest
import uuid
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes import applications, jobs, profile, runs as routes
from api.routes.search_config import pipeline_router, router as search_router
from core import database, runs
from core.websocket import ConnectionManager, EVENT_CHANNEL
from models.application import AgentEvent, Application
from models.job import Job
from models.profile import UserProfile
from models.run import TaskRun
from models.search_config import SearchConfig
from workers.scheduler import tick


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.admin_engine = None
        postgres_url = os.environ.get("JOBFORGE_TEST_DATABASE_URL")
        if postgres_url:
            self.schema = f"jobforge_test_{uuid.uuid4().hex}"
            self.admin_engine = create_async_engine(postgres_url)
            async with self.admin_engine.begin() as connection:
                await connection.execute(CreateSchema(self.schema))
            self.engine = create_async_engine(postgres_url, connect_args={"server_settings": {"search_path": self.schema}})
        else:
            self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.directory.name}/test.db")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        for target, value in (("engine", self.engine), ("AsyncSessionLocal", self.sessions)):
            patcher = patch.object(database, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        publisher = patch("core.websocket.Redis.from_url")
        self.redis_factory = publisher.start()
        self.addCleanup(publisher.stop)
        self.redis = self.redis_factory.return_value.__aenter__.return_value
        self.redis.publish = AsyncMock()
        sender = patch("workers.celery_app.celery_app.send_task")
        self.sender = sender.start()
        self.addCleanup(sender.stop)
        descriptions = patch("core.job_descriptions.fetch_description", new=AsyncMock(return_value="Job requirements. " * 30))
        descriptions.start()
        self.addCleanup(descriptions.stop)
        await database.init_db()
        app = FastAPI()
        for router in (routes.router, pipeline_router, search_router, jobs.router, applications.router, profile.router):
            app.include_router(router)
        self.client = AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")
        async with self.sessions() as db:
            db.add(UserProfile(full_name="Candidate", email="candidate@example.com", skills=[]))
            config = SearchConfig(keywords=["Engineer"], locations=["Remote"], portals=["remoteok"], auto_research_top_n=0)
            db.add(config)
            job = Job(title="Engineer", company="Example", portal="remoteok", url="https://example.com/job", description="Job requirements. " * 30)
            db.add(job)
            await db.commit()
            self.config_id = config.id
            self.job_id = job.id

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        if self.admin_engine:
            async with self.admin_engine.begin() as connection:
                await connection.execute(DropSchema(self.schema, cascade=True))
            await self.admin_engine.dispose()
        self.directory.cleanup()

    async def enqueue(self, kind="rank", **options):
        async with self.sessions() as db:
            run, created = await runs.enqueue_run(db, kind, dispatch=False, **options)
            self.assertTrue(created)
            return run

    async def get(self, run_id):
        async with self.sessions() as db:
            return await db.get(TaskRun, run_id)

    async def test_duplicate_work_shares_run_and_duplicate_delivery_executes_once(self):
        run = await self.enqueue()
        async with self.sessions() as db:
            duplicate, created = await runs.enqueue_run(db, "pipeline", dispatch=False)
            self.assertFalse(created)
            self.assertEqual(duplicate.id, run.id)
        handler = AsyncMock(return_value={"jobs_ranked": 1})
        with patch("workers.handlers.perform_run", new=handler):
            outcomes = await asyncio.gather(runs.execute_run(run.id), runs.execute_run(run.id))
        self.assertEqual(handler.await_count, 1)
        self.assertIn("not_claimed", outcomes)
        self.assertIn("succeeded", outcomes)
        self.assertIsNone((await self.get(run.id)).active_key)
        await self.enqueue()

    async def test_concurrent_enqueue_creates_only_one_durable_run(self):
        async def enqueue():
            async with self.sessions() as db:
                record, created = await runs.enqueue_run(db, "pipeline", dispatch=False)
                return record.id, created
        first, second = await asyncio.gather(enqueue(), enqueue())
        self.assertEqual(first[0], second[0])
        self.assertEqual(int(first[1]) + int(second[1]), 1)

    async def test_active_research_is_protected_from_stale_cleanup_and_clear(self):
        from agents.pipeline import _cleanup_stale_jobs
        await self.enqueue("research", job_id=self.job_id)
        async with self.sessions() as db:
            job = await db.get(Job, self.job_id)
            job.posted_at = datetime.utcnow() - timedelta(days=60)
            await db.commit()
            self.assertEqual(await _cleanup_stale_jobs(db, 7), 0)
            await db.commit()
        response = await self.client.delete("/api/jobs/clear")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], 0)

    async def test_permanent_application_deletion_removes_finished_run_history(self):
        async with self.sessions() as db:
            db.add(Application(job_id=self.job_id, status="saved"))
            run = TaskRun(kind="research", status="failed", job_id=self.job_id, error="Old failed analysis")
            db.add(run)
            await db.flush()
            run_id = run.id
            db.add(AgentEvent(agent="pipeline", status="done", message="Old progress", run_id=run_id))
            await db.commit()
        self.assertEqual((await self.client.delete(f"/api/applications/{self.job_id}")).status_code, 200)
        self.assertEqual((await self.client.get(f"/api/runs/{run_id}")).status_code, 404)
        self.assertEqual((await self.client.get(f"/api/runs/events?run_id={run_id}")).json()["events"], [])

    async def test_stage_results_and_event_history_survive_new_http_client(self):
        run = await self.enqueue()

        async def perform(record):
            await runs.stage("rank", "Ranked first batch", 3, 10, result={"jobs_ranked": 3})
            await runs.stage("rank", "Ranking complete", 10, 10, done=True)
            return {"jobs_ranked": 10}

        with patch("workers.handlers.perform_run", new=perform):
            await runs.execute_run(run.id)
        response = await self.client.get(f"/api/runs/{run.id}")
        self.assertEqual(response.json()["status"], "succeeded")
        self.assertEqual(response.json()["result"]["jobs_ranked"], 10)
        self.assertEqual(response.json()["stages"][-1]["completed"], 10)
        events = (await self.client.get(f"/api/runs/events?run_id={run.id}")).json()["events"]
        self.assertGreaterEqual(len(events), 5)
        self.assertNotIn("payload", response.json())
        self.assertNotIn("execution_token", response.json())
        self.redis.publish.assert_awaited()
        channel, published = self.redis.publish.await_args.args
        self.assertEqual(channel, EVENT_CHANNEL)
        self.assertEqual(json.loads(published)["run_id"], run.id)

    async def test_failures_retry_to_limit_and_keep_stage_failure_details(self):
        run = await self.enqueue(max_attempts=2)

        async def fail(record):
            await runs.stage("rank", "Scoring jobs", result={"jobs_ranked": 4})
            raise RuntimeError("Model is offline")

        with patch("workers.handlers.perform_run", new=fail):
            self.assertEqual(await runs.execute_run(run.id), "retrying")
            retrying = await self.get(run.id)
            self.assertEqual(retrying.attempts, 1)
            self.assertIsNotNone(retrying.next_retry_at)
            self.assertEqual(retrying.result["jobs_ranked"], 4)
            self.assertEqual(retrying.stages[-1]["status"], "failed")
            self.assertEqual(await runs.execute_run(run.id), "not_claimed")
            async with self.sessions() as db:
                await db.execute(update(TaskRun).where(TaskRun.id == run.id).values(next_retry_at=datetime.utcnow() - timedelta(seconds=1)))
                await db.commit()
            self.assertEqual(await runs.execute_run(run.id), "failed")
        failed = await self.get(run.id)
        self.assertEqual(failed.attempts, 2)
        self.assertEqual(failed.error_type, "RuntimeError")
        self.assertIn("Model is offline", failed.traceback)
        self.assertIsNone(failed.active_key)

    async def test_successful_retry_does_not_inherit_previous_attempt_errors(self):
        run = await self.enqueue()
        with patch("workers.handlers.perform_run", new=AsyncMock(side_effect=RuntimeError("Temporary error"))):
            await runs.execute_run(run.id)
        async with self.sessions() as db:
            await db.execute(update(TaskRun).where(TaskRun.id == run.id).values(next_retry_at=datetime.utcnow() - timedelta(seconds=1)))
            await db.commit()
        with patch("workers.handlers.perform_run", new=AsyncMock(return_value={"jobs_ranked": 0})):
            self.assertEqual(await runs.execute_run(run.id), "succeeded")
        self.assertIsNone((await self.get(run.id)).error)

    async def test_partial_portal_errors_are_visible_and_can_be_retried(self):
        run = await self.enqueue()

        async def partial(record):
            await ConnectionManager().emit_agent_event("search", "error", "Portal blocked this request")
            return {"new_jobs_found": 2}

        with patch("workers.handlers.perform_run", new=partial):
            self.assertEqual(await runs.execute_run(run.id), "partial")
        response = await self.client.post(f"/api/runs/{run.id}/retry", json={"max_attempts": 2})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertNotEqual(response.json()["run_id"], run.id)
        self.assertEqual(response.json()["run"]["retry_of"], run.id)
        self.assertEqual(response.json()["run"]["max_attempts"], 2)
        self.assertEqual((await self.get(run.id)).status, "partial")
        self.assertEqual((await self.client.post(f"/api/runs/{response.json()['run_id']}/retry")).status_code, 409)

    async def test_pipeline_api_queues_snapshot_without_running_agents_in_request(self):
        with patch("workers.handlers.perform_run", new=AsyncMock()) as handler:
            response = await self.client.post("/api/pipeline/run")
            duplicate = await self.client.post("/api/pipeline/run")
            handler.assert_not_awaited()
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["run_id"], duplicate.json()["run_id"])
        run = await self.get(response.json()["run_id"])
        self.assertEqual(run.payload["keywords"], ["Engineer"])
        self.assertEqual(run.config_id, self.config_id)
        self.sender.assert_called_once()

    async def test_pipeline_commits_jobs_before_ranking_failure(self):
        response = await self.client.post("/api/pipeline/run")
        with patch("agents.search.SearchAgent.run", new=AsyncMock(return_value=[{
            "title": "New role", "company": "New company", "portal": "remoteok", "url": "https://example.com/new",
        }])), patch("agents.rank.RankAgent.run", new=AsyncMock(side_effect=RuntimeError("Model disconnected"))):
            self.assertEqual(await runs.execute_run(response.json()["run_id"]), "retrying")
        run = await self.get(response.json()["run_id"])
        self.assertEqual(run.stage, "rank")
        self.assertEqual(run.result["new_jobs_found"], 1)
        async with self.sessions() as db:
            self.assertIsNotNone((await db.execute(select(Job).where(Job.url == "https://example.com/new"))).scalar_one_or_none())

    async def test_pipeline_tracks_child_research_and_finishes_after_it(self):
        async with self.sessions() as db:
            config = await db.get(SearchConfig, self.config_id)
            config.auto_research_top_n = 1
            await db.commit()
        response = await self.client.post("/api/pipeline/run")

        async def score(agent, jobs, profile):
            return [{"job_id": job.id, "overall": 80, "strengths": [], "gaps": []} for job in jobs]

        analysis = {"fit_score": 80, "tech_score": 80, "exp_score": 80, "location_score": 80, "growth_score": 80,
                    "strengths": [], "gaps": [], "fit_summary": "Good fit", "talking_points": []}
        with patch("agents.search.SearchAgent.run", new=AsyncMock(return_value=[])), patch("agents.rank.RankAgent.run", new=score), patch("agents.research.ResearchAgent._analyse", new=AsyncMock(return_value=analysis)):
            self.assertEqual(await runs.execute_run(response.json()["run_id"]), "succeeded")
        detail = (await self.client.get(f"/api/runs/{response.json()['run_id']}")).json()
        self.assertEqual(len(detail["children"]), 1)
        self.assertEqual(detail["children"][0]["status"], "succeeded")
        self.assertEqual(detail["stages"][-1]["name"], "research")
        self.assertEqual(detail["result"]["jobs_researched"], 1)

    async def test_rank_drains_more_than_fifty_jobs(self):
        async with self.sessions() as db:
            db.add_all(Job(title=f"Role {index}", company=f"Company {index}", portal="remoteok", url=f"https://example.com/{index}") for index in range(51))
            await db.commit()
        run = await self.enqueue()

        async def score(agent, jobs, profile):
            return [{"job_id": job.id, "overall": 80} for job in jobs]

        with patch("agents.rank.RankAgent.run", new=score):
            self.assertEqual(await runs.execute_run(run.id), "succeeded")
        self.assertEqual((await self.get(run.id)).result["jobs_ranked"], 52)

    async def test_automatic_retry_keeps_original_research_targets(self):
        run = await self.enqueue("pipeline")
        async with self.sessions() as db:
            job = await db.get(Job, self.job_id)
            job.fit_score = 80
            job.researched_at = datetime.utcnow()
            record = await db.get(TaskRun, run.id)
            record.result = {"research_job_ids": [self.job_id]}
            db.add(Job(title="Another role", company="Other", portal="remoteok", fit_score=90, url="https://example.com/another"))
            await db.commit()

        async def perform(record):
            from agents.pipeline import _auto_research
            return {"jobs_researched": await _auto_research(None, 1)}

        with patch("workers.handlers.perform_run", new=perform):
            self.assertEqual(await runs.execute_run(run.id), "succeeded")
        async with self.sessions() as db:
            children = (await db.execute(select(TaskRun).where(TaskRun.parent_id == run.id))).scalars().all()
            self.assertEqual(children, [])
            self.assertEqual((await db.get(TaskRun, run.id)).result["jobs_researched"], 1)

    async def test_failed_research_does_not_save_fabricated_fit_score(self):
        run = await self.enqueue("research", job_id=self.job_id, max_attempts=1)
        with patch("agents.research.ResearchAgent._analyse", new=AsyncMock(side_effect=RuntimeError("Model is offline"))):
            self.assertEqual(await runs.execute_run(run.id), "failed")
        async with self.sessions() as db:
            job = await db.get(Job, self.job_id)
            self.assertIsNone(job.fit_score)
            self.assertIsNone(job.researched_at)

    async def test_recovery_requeues_expired_worker_and_fences_old_commits(self):
        run = await self.enqueue(max_attempts=2)
        async with self.sessions() as db:
            await db.execute(update(TaskRun).where(TaskRun.id == run.id).values(
                status="running", attempts=1, execution_token="dead-worker",
                created_at=datetime.utcnow() - timedelta(minutes=5),
                lease_expires_at=datetime.utcnow() - timedelta(seconds=1),
            ))
            await db.commit()
        await runs.recover_and_dispatch()
        recovered = await self.get(run.id)
        self.assertEqual(recovered.status, "retrying")
        self.assertEqual(recovered.error_type, "WorkerInterrupted")
        self.sender.assert_called_once()
        token = runs.current_run.set((run.id, "dead-worker"))
        try:
            async with self.sessions() as db:
                job = await db.get(Job, self.job_id)
                job.title = "Obsolete worker overwrite"
                with self.assertRaises(runs.RunLost):
                    await runs.commit_owned(db)
        finally:
            runs.current_run.reset(token)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Job, self.job_id)).title, "Engineer")

    async def test_recovery_preserves_healthy_workers(self):
        run = await self.enqueue()
        async with self.sessions() as db:
            await db.execute(update(TaskRun).where(TaskRun.id == run.id).values(status="running", lease_expires_at=datetime.utcnow() + timedelta(minutes=2)))
            await db.commit()
        await runs.recover_and_dispatch()
        self.assertEqual((await self.get(run.id)).status, "running")
        self.sender.assert_not_called()

    async def test_exhausted_document_worker_releases_lock_and_keeps_application_stage(self):
        async with self.sessions() as db:
            db.add(Application(job_id=self.job_id, status="applied", document_status="generating"))
            await db.commit()
        run = await self.enqueue("docgen", job_id=self.job_id, max_attempts=1)
        async with self.sessions() as db:
            await db.execute(update(TaskRun).where(TaskRun.id == run.id).values(status="running", attempts=1, lease_expires_at=datetime.utcnow() - timedelta(seconds=1)))
            await db.commit()
        await runs.recover_and_dispatch()
        self.assertEqual((await self.get(run.id)).status, "failed")
        async with self.sessions() as db:
            application = (await db.execute(select(Application))).scalar_one()
            self.assertEqual(application.status, "applied")
            self.assertEqual(application.document_status, "failed")

    async def test_broker_outage_keeps_durable_queued_work_and_dispatch_error(self):
        run = await self.enqueue()
        self.sender.side_effect = RuntimeError("Redis unavailable")
        await runs.dispatch_run(run.id)
        waiting = await self.get(run.id)
        self.assertEqual(waiting.status, "queued")
        self.assertIn("Redis unavailable", waiting.dispatch_error)
        self.sender.side_effect = None
        async with self.sessions() as db:
            await db.execute(update(TaskRun).where(TaskRun.id == run.id).values(created_at=datetime.utcnow() - timedelta(minutes=2)))
            await db.commit()
        await runs.recover_and_dispatch()
        self.assertIsNone((await self.get(run.id)).dispatch_error)

    async def test_scheduler_honors_interval_and_manual_only_and_avoids_duplicates(self):
        async with self.sessions() as db:
            config = await db.get(SearchConfig, self.config_id)
            config.run_every_hours = 0
            config.created_at = datetime.utcnow() - timedelta(days=2)
            await db.commit()
        await tick()
        self.sender.assert_not_called()
        async with self.sessions() as db:
            config = await db.get(SearchConfig, self.config_id)
            config.run_every_hours = 4
            config.created_at = datetime.utcnow() - timedelta(hours=3)
            await db.commit()
        await tick()
        self.sender.assert_not_called()
        async with self.sessions() as db:
            config = await db.get(SearchConfig, self.config_id)
            config.created_at = datetime.utcnow() - timedelta(hours=5)
            await db.commit()
        await tick()
        await tick()
        self.sender.assert_called_once()
        async with self.sessions() as db:
            scheduled = (await db.execute(select(TaskRun))).scalar_one()
            self.assertEqual(scheduled.trigger, "scheduled")
            self.assertEqual(scheduled.payload["keywords"], ["Engineer"])

    async def test_resume_parse_can_be_recovered_after_leaving_page(self):
        response = await self.client.post("/api/profile/parse-resume", files={"file": ("resume.pdf", b"test PDF", "application/pdf")})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertNotIn("payload", response.json()["run"])
        with patch("core.resume_parser.ResumeParser.parse_pdf", new=AsyncMock(return_value={"full_name": "Parsed candidate"})):
            self.assertEqual(await runs.execute_run(response.json()["run_id"]), "succeeded")
        recovered = (await self.client.get(f"/api/runs/{response.json()['run_id']}")).json()
        self.assertEqual(recovered["result"]["parsed"]["full_name"], "Parsed candidate")
        self.assertEqual((await self.get(response.json()["run_id"])).payload, {})

    async def test_api_rejects_invalid_schedule_and_missing_pipeline_prerequisites(self):
        response = await self.client.post("/api/search-config", json={"keywords": ["Engineer"], "run_every_hours": -1})
        self.assertEqual(response.status_code, 422)
        async with self.sessions() as db:
            config = await db.get(SearchConfig, self.config_id)
            config.active = False
            await db.commit()
        self.assertEqual((await self.client.post("/api/pipeline/run")).status_code, 400)
        self.sender.assert_not_called()

    async def test_redis_listener_forwards_worker_events_to_api_websockets(self):
        manager = ConnectionManager()
        websocket = AsyncMock()
        await manager.connect(websocket)
        delivered = asyncio.Event()
        data = {"id": "event-1", "agent": "search", "status": "done", "message": "Found jobs", "extra": {}}

        async def messages():
            yield {"type": "message", "data": json.dumps(data)}
            await asyncio.Event().wait()

        self.redis.pubsub = MagicMock()
        subscription = self.redis.pubsub.return_value.__aenter__.return_value
        subscription.listen = MagicMock(side_effect=messages)
        websocket.send_text.side_effect = lambda payload: delivered.set()
        listener = asyncio.create_task(manager.listen())
        try:
            await asyncio.wait_for(delivered.wait(), timeout=2)
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
        payload = json.loads(websocket.send_text.await_args.args[0])
        self.assertEqual(payload["event"], "agent_event")
        self.assertEqual(payload["data"]["id"], "event-1")

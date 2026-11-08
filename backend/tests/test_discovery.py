import unittest
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes.jobs import router as jobs_router
from api.routes.search_config import router as config_router, pipeline_router
from core import database, runs
from models.application import Application
from models.job import Job
from models.profile import UserProfile
from models.search_config import SearchConfig
from models.run import TaskRun


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.directory.name}/test.db")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        for target, value in (("engine", self.engine), ("AsyncSessionLocal", self.sessions)):
            patcher = patch.object(database, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sender = patch("workers.celery_app.celery_app.send_task")
        sender.start()
        self.addCleanup(sender.stop)
        publisher = patch("core.websocket.Redis.from_url")
        factory = publisher.start()
        self.addCleanup(publisher.stop)
        factory.return_value.__aenter__.return_value.publish = AsyncMock()
        await database.init_db()
        app = FastAPI()
        for router in (jobs_router, config_router, pipeline_router):
            app.include_router(router)
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        async with self.sessions() as db:
            db.add(UserProfile(full_name="Candidate", email="test@example.com"))
            for index in range(125):
                job = Job(title=f"Python Engineer {index:03}", company="Acme" if index % 2 else "Beta",
                          url=f"https://example.com/{index}", portal="remoteok" if index % 2 else "linkedin",
                          location="Berlin" if index % 2 else "London", remote=bool(index % 2),
                          fit_score=index % 100, posted_at=datetime.utcnow() - timedelta(days=index % 20),
                          salary_min=100000, salary_max=150000, salary_currency="USD", salary_period="year")
                db.add(job)
            db.add(Job(title="Dismissed", company="Hidden", url="https://example.com/hidden", portal="linkedin", status="dismissed"))
            await db.commit()

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()
        self.directory.cleanup()

    async def test_server_pagination_total_and_deterministic_order(self):
        first = (await self.client.get("/api/jobs?limit=100&sort=company")).json()
        second = (await self.client.get("/api/jobs?limit=100&offset=100&sort=company")).json()
        self.assertEqual(first["total"], 125)
        self.assertEqual(first["count"], 100)
        self.assertTrue(first["has_more"])
        self.assertEqual(second["count"], 25)
        self.assertFalse(second["has_more"])
        self.assertFalse({job["id"] for job in first["jobs"]} & {job["id"] for job in second["jobs"]})
        self.assertEqual((await self.client.get("/api/jobs?offset=1000")).json()["total"], 125)

    async def test_combined_filters_are_applied_before_pagination(self):
        result = (await self.client.get("/api/jobs", params={"keyword": "python", "company": "ACME", "location": "berlin", "portal": "remoteok", "remote": True, "min_score": 70, "limit": 2})).json()
        self.assertEqual(result["count"], 2)
        self.assertGreater(result["total"], 2)
        self.assertTrue(all(job["fit_score"] >= 70 and job["company"] == "Acme" for job in result["jobs"]))
        self.assertEqual((await self.client.get("/api/jobs?keyword=%25")).json()["total"], 0)

    async def test_saved_view_uses_application_lifecycle(self):
        async with self.sessions() as db:
            job = (await db.execute(select(Job).limit(1))).scalar_one()
            db.add(Application(job_id=job.id, status="saved"))
            await db.commit()
        result = (await self.client.get("/api/jobs?application_status=saved")).json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["jobs"][0]["id"], job.id)

    async def test_salary_overlap_currency_and_period(self):
        params = {"salary_min": 140000, "salary_max": 160000, "salary_currency": "USD", "salary_period": "year", "sort": "salary"}
        self.assertEqual((await self.client.get("/api/jobs", params=params)).json()["total"], 125)
        for field, value in (("salary_currency", "INR"), ("salary_period", "month"), ("salary_min", 160000)):
            changed = {**params, field: value}
            self.assertEqual((await self.client.get("/api/jobs", params=changed)).json()["total"], 0)
        self.assertEqual((await self.client.get("/api/jobs?salary_min=100")).status_code, 422)
        self.assertEqual((await self.client.get("/api/jobs?salary_min=200&salary_max=100&salary_currency=USD")).status_code, 422)

    async def test_open_ended_salary_ranges_and_unknown_amounts(self):
        for title, amounts in (("At least", {"salary_min": 100}), ("Up to", {"salary_max": 100}), ("Unknown", {})):
            response = await self.client.post("/api/jobs/import", json={"title": title, "company": "Example", "description": "Requirements", "salary_currency": "USD", "salary_period": "hour", **amounts})
            self.assertEqual(response.status_code, 201)
        above = (await self.client.get("/api/jobs?salary_min=200&salary_currency=USD&salary_period=hour")).json()
        below = (await self.client.get("/api/jobs?salary_max=50&salary_currency=USD&salary_period=hour")).json()
        self.assertEqual([job["title"] for job in above["jobs"]], ["At least"])
        self.assertEqual([job["title"] for job in below["jobs"]], ["Up to"])
        self.assertEqual((await self.client.get("/api/jobs?sort=salary&salary_currency=USD&salary_period=hour")).json()["total"], 2)

    async def test_date_filter_excludes_unknown_dates_and_sorting(self):
        result = (await self.client.get("/api/jobs?posted_within_days=3&sort=posted&limit=100")).json()
        cutoff = datetime.utcnow() - timedelta(days=3)
        self.assertTrue(all(datetime.fromisoformat(job["posted_at"]) >= cutoff for job in result["jobs"]))
        dates = [job["posted_at"] for job in result["jobs"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        for query in ("limit=0", "offset=-1", "sort=invalid", "posted_within_days=0"):
            self.assertEqual((await self.client.get(f"/api/jobs?{query}")).status_code, 422)

    async def test_manual_import_url_or_description_without_network_or_application(self):
        with patch("httpx.AsyncClient.get", side_effect=AssertionError("Import must not fetch URLs")):
            response = await self.client.post("/api/jobs/import", json={"title": "Manual role", "company": "Example", "url": "https://example.org/job#apply"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["portal"], "manual")
        self.assertEqual(response.json()["status"], "new")
        self.assertEqual(response.json()["url"], "https://example.org/job")
        duplicate = await self.client.post("/api/jobs/import", json={"title": "Duplicate", "company": "Example", "url": "https://example.org/job#other"})
        self.assertEqual(duplicate.status_code, 409)
        pasted = await self.client.post("/api/jobs/import", json={"title": "Pasted role", "company": "Example", "description": "Python and AWS", "salary_min": 100, "salary_max": 200, "salary_currency": "usd", "salary_period": "hour"})
        self.assertEqual(pasted.status_code, 201, pasted.text)
        self.assertTrue(pasted.json()["url"].startswith("manual:"))
        self.assertEqual(pasted.json()["salary_currency"], "USD")
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(Application))).scalars().all(), [])

    async def test_manual_validation_and_cleanup_protection(self):
        base = {"title": "Manual", "company": "Example", "description": "Requirements"}
        for change in ({"title": " "}, {"url": "file:///etc/passwd"}, {"url": "https://user:pass@example.com"}, {"description": " "}, {"salary_min": 100}, {"salary_min": 200, "salary_max": 100, "salary_currency": "USD", "salary_period": "year"}):
            self.assertEqual((await self.client.post("/api/jobs/import", json={**base, **change})).status_code, 422)
        response = await self.client.post("/api/jobs/import", json={**base, "posted_at": "2020-01-01T00:00:00+05:30"})
        self.assertEqual(response.status_code, 201)
        from agents.pipeline import _cleanup_stale_jobs
        async with self.sessions() as db:
            await _cleanup_stale_jobs(db, 1)
            self.assertIsNotNone(await db.get(Job, response.json()["id"]))

    async def test_named_configurations_update_in_place_and_explicit_run(self):
        original = {"name": "Germany Backend", "keywords": ["Python"], "locations": ["Germany"], "run_every_hours": 0}
        first = (await self.client.post("/api/search-config", json=original)).json()["id"]
        second = (await self.client.post("/api/search-config", json={**original, "name": "Singapore Lead", "locations": ["Singapore"]})).json()["id"]
        updated = await self.client.put(f"/api/search-config/{first}", json={**original, "keywords": ["Backend"]})
        self.assertEqual(updated.status_code, 200)
        configs = (await self.client.get("/api/search-config/all")).json()["configs"]
        self.assertEqual(len(configs), 2)
        self.assertTrue(all(config["active"] for config in configs))
        response = await self.client.post(f"/api/pipeline/run?config_id={second}")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["run"]["config_id"], second)
        self.assertEqual(response.json()["run"]["label"], "Singapore Lead")
        self.assertEqual((await self.client.post("/api/pipeline/run?config_id=999999")).status_code, 400)

    async def test_scheduler_keeps_profiles_independent_and_selects_oldest_due(self):
        from workers.scheduler import tick
        async with self.sessions() as db:
            first = SearchConfig(name="Oldest due", keywords=["Python"], locations=["Germany"], run_every_hours=1, created_at=datetime.utcnow() - timedelta(hours=3))
            second = SearchConfig(name="Next due", keywords=["Lead"], locations=["Singapore"], run_every_hours=1, created_at=datetime.utcnow() - timedelta(hours=2))
            paused = SearchConfig(name="Paused", keywords=["Python"], locations=["India"], active=False, run_every_hours=1, created_at=datetime.utcnow() - timedelta(days=1))
            db.add_all([first, second, paused])
            await db.commit()
        await tick()
        async with self.sessions() as db:
            run = (await db.execute(select(TaskRun))).scalar_one()
            self.assertEqual(run.config_id, first.id)
            run.status = "succeeded"
            run.active_key = None
            await db.commit()
        await tick()
        async with self.sessions() as db:
            records = (await db.execute(select(TaskRun).order_by(TaskRun.created_at))).scalars().all()
            self.assertEqual([run.config_id for run in records], [first.id, second.id])

    async def test_existing_database_migrates_without_losing_jobs(self):
        async with self.sessions() as db:
            config = SearchConfig(keywords=["Python"], locations=["Germany"])
            db.add(config)
            await db.commit()
        async with self.engine.begin() as connection:
            for column in ("salary_min", "salary_max", "salary_currency", "salary_period"):
                await connection.execute(text(f"ALTER TABLE jobs DROP COLUMN {column}"))
            await connection.execute(text("ALTER TABLE search_configs DROP COLUMN name"))
        await database.init_db()
        await database.init_db()
        async with self.sessions() as db:
            self.assertEqual((await db.get(SearchConfig, config.id)).name, "Default search")
            records = (await db.execute(select(Job))).scalars().all()
            self.assertEqual(len(records), 126)
            self.assertTrue(all(job.salary_min is None for job in records))

    async def test_imported_description_is_used_without_fetching(self):
        from agents.research import ResearchAgent
        response = await self.client.post("/api/jobs/import", json={"title": "Pasted", "company": "Example", "description": "Short pasted requirements", "url": "http://localhost/private"})
        async with self.sessions() as db:
            agent = ResearchAgent(db=db)
            agent.emit = AsyncMock()
            analysis = {"fit_score": 80, "strengths": [], "gaps": []}
            with patch.object(agent, "_fetch_description", new=AsyncMock()) as fetch, patch.object(agent, "_analyse", new=AsyncMock(return_value=analysis)):
                await agent.run(response.json()["id"], {})
                fetch.assert_not_awaited()

    async def test_all_portal_failures_are_persisted_and_fail_the_run(self):
        from agents.search import SearchAgent
        from workers.scheduler import snapshot
        async with self.sessions() as db:
            config = SearchConfig(name="Failed portal", keywords=["Python"], locations=["Remote"], portals=["linkedin"], auto_research_top_n=0)
            db.add(config)
            await db.commit()
            run, created = await runs.enqueue_run(db, "pipeline", snapshot(config), config_id=config.id, dispatch=False, max_attempts=1)
        with patch.object(SearchAgent, "_search_one", new=AsyncMock(side_effect=RuntimeError("Portal unavailable"))), patch("agents.search.asyncio.sleep", new=AsyncMock()):
            outcome = await runs.execute_run(run.id)
        self.assertEqual(outcome, "failed")
        async with self.sessions() as db:
            record = await db.get(TaskRun, run.id)
            self.assertEqual(record.result["portal_reports"]["linkedin"]["status"], "failed")
            self.assertIn("All configured portals failed", record.error)

    async def test_store_refreshes_missing_structured_salary_without_duplicate(self):
        from agents.pipeline import store_jobs
        async with self.sessions() as db:
            existing = (await db.execute(select(Job).where(Job.url == "https://example.com/0"))).scalar_one()
            existing.salary_min = None
            count = await store_jobs(db, [{"url": existing.url, "salary_min": 110000}])
            self.assertEqual(count, 0)
            self.assertEqual(existing.salary_min, 110000)

    async def test_one_failed_portal_retains_successful_results_and_reports_partial(self):
        from agents.search import SearchAgent
        from workers.scheduler import snapshot
        async with self.sessions() as db:
            config = SearchConfig(name="Mixed portals", keywords=["Python"], locations=["Remote"], portals=["remoteok", "linkedin"], auto_research_top_n=0)
            db.add(config)
            await db.commit()
            run, created = await runs.enqueue_run(db, "pipeline", snapshot(config), config_id=config.id, dispatch=False, max_attempts=1)

        async def search(agent, portal, *arguments, **options):
            if portal == "linkedin":
                raise RuntimeError("Rate limited")
            return [{"url": "https://example.org/success", "title": "Success", "company": "Example", "portal": "remoteok"}]

        with patch.object(SearchAgent, "_search_one", new=search), patch("agents.search.asyncio.sleep", new=AsyncMock()), patch("workers.handlers.rank_pending", new=AsyncMock(return_value=0)):
            self.assertEqual(await runs.execute_run(run.id), "partial")
        async with self.sessions() as db:
            self.assertIsNotNone((await db.execute(select(Job).where(Job.url == "https://example.org/success"))).scalar_one_or_none())
            record = await db.get(TaskRun, run.id)
            self.assertEqual(record.result["portal_reports"]["remoteok"]["status"], "succeeded")

    async def test_narrow_configuration_does_not_clean_another_profiles_window(self):
        from agents.pipeline import run_pipeline
        async with self.sessions() as db:
            narrow = SearchConfig(name="Today", keywords=["Python"], locations=["Berlin"], posted_within_days=1, auto_research_top_n=0)
            wide = SearchConfig(name="Monthly", keywords=["Lead"], locations=["Singapore"], posted_within_days=30, auto_research_top_n=0)
            db.add_all([narrow, wide])
            await db.commit()
            job = (await db.execute(select(Job).where(Job.url == "https://example.com/10"))).scalar_one()
            with patch("agents.search.SearchAgent.run", new=AsyncMock(return_value=[])), patch("workers.handlers.rank_pending", new=AsyncMock(return_value=0)):
                await run_pipeline(db, config_data={field: getattr(narrow, field) for field in ("keywords", "locations", "portals", "remote_only", "posted_within_days", "auto_research_top_n")}, config_id=narrow.id)
            self.assertIsNotNone(await db.get(Job, job.id))


class SearchReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_200_verification_page_is_not_reported_as_empty_success(self):
        from agents.search import SearchAgent
        agent = SearchAgent()
        response = AsyncMock()
        response.status_code = 200
        response.text = "<html><title>Just a moment...</title></html>"
        with patch("agents.search.httpx.AsyncClient") as client:
            client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            with patch.object(agent, "emit", new=AsyncMock()) as emit:
                self.assertIsNone(await agent._fetch("https://example.com/search"))
                self.assertEqual(emit.call_args.args[0], "error")

    async def test_portal_failures_and_dates_reported_per_search(self):
        from agents.search import SearchAgent
        agent = SearchAgent()
        recent = datetime.utcnow()

        async def search(portal, keyword, location, remote_only, **options):
            if portal == "linkedin":
                await agent.emit("error", "LinkedIn HTTP 429", {"portal": portal})
                return []
            return [{"url": "https://example.com/new", "posted_at": recent},
                    {"url": "https://example.com/old", "posted_at": recent - timedelta(days=8)},
                    {"url": "https://example.com/undated", "posted_at": None}]

        with patch.object(agent, "_search_one", side_effect=search), patch("agents.base.BaseAgent.emit", new=AsyncMock()), patch("agents.search.asyncio.sleep", new=AsyncMock()):
            results = await agent.run(["Python"], ["Remote"], ["remoteok", "linkedin"], posted_within_days=3)
        self.assertEqual(len(results), 2)
        self.assertEqual(agent.portal_reports["linkedin"]["status"], "failed")
        report = agent.portal_reports["remoteok"]["searches"][0]
        self.assertEqual(report["excluded_old"], 1)
        self.assertEqual(report["unknown_date"], 1)
        self.assertEqual(report["status"], "succeeded")

    async def test_linkedin_honors_days_and_dates_normalize_utc(self):
        from agents.search import SearchAgent, _safe_date
        agent = SearchAgent()
        with patch.object(agent, "_fetch", new=AsyncMock(return_value="<html></html>")) as fetch:
            await agent._search_linkedin("Python", "Berlin", False, posted_within_days=3)
        self.assertEqual(fetch.call_args.kwargs["params"]["f_TPR"], "r259200")
        self.assertEqual(_safe_date("2026-01-01T10:00:00+05:30"), datetime(2026, 1, 1, 4, 30))

    async def test_linkedin_remote_filter_preserves_remote_jobs_with_city_locations(self):
        from agents.search import SearchAgent
        agent = SearchAgent()
        html = '<li><a class="base-card__full-link" href="https://example.org/job"></a><h3 class="base-search-card__title">Python Engineer</h3><h4 class="base-search-card__subtitle">Example</h4><span class="job-search-card__location">Berlin</span></li>'
        with patch.object(agent, "_fetch", new=AsyncMock(return_value=html)):
            results = await agent._search_linkedin("Python", "Berlin", True)
        self.assertTrue(results[0]["remote"])

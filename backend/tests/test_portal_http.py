"""Exercise rate limits with fake HTTP responses, never real job portals."""

import asyncio
import os
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from agents.search import SearchAgent
from core import database
from core.config import settings
from core.portal_http import PortalHTTP, PortalUnavailable, RequestPolicy, retry_time, raise_if_all_portals_failed
from models.portal_request import PortalRequestState


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 19, 12)

    def now(self):
        return self.value

    async def sleep(self, seconds):
        self.value += timedelta(seconds=seconds)


class PortalFixtures:
    def setUp(self):
        self.clock = Clock()
        self.policy = RequestPolicy(now=self.clock.now, sleep=self.clock.sleep)

    def client(self, handler, persistent=False):
        policy = RequestPolicy(persistent=True, now=self.clock.now, sleep=self.clock.sleep) if persistent else self.policy
        return PortalHTTP(policy=policy, emit=AsyncMock(), transport=httpx.MockTransport(handler))


class PortalHTTPTests(PortalFixtures, unittest.IsolatedAsyncioTestCase):
    def test_retry_after_seconds_dates_and_missing_values(self):
        now = self.clock.now()
        self.assertEqual(retry_time("120", now), now + timedelta(seconds=120))
        date = format_datetime((now + timedelta(minutes=10)).replace(tzinfo=timezone.utc), usegmt=True)
        self.assertEqual(retry_time(date, now), now + timedelta(minutes=10))
        for value in (None, "invalid", "-10", "9" * 500):
            self.assertEqual(retry_time(value, now), now + timedelta(seconds=900))
        self.assertGreater(retry_time("0", now), now)

    async def test_429_stops_more_requests_and_announces_the_portal_once(self):
        handler = AsyncMock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))
        client = self.client(handler)
        for keyword in ("Python", "AWS", "Cloud"):
            with self.assertRaises(PortalUnavailable) as caught:
                await client.get("https://www.linkedin.com/search", params={"keywords": keyword})
            self.assertEqual(caught.exception.until, self.clock.now() + timedelta(seconds=120))
        self.assertEqual(handler.await_count, 1)
        client.emit.assert_awaited_once()
        message = client.emit.call_args.args[1]
        self.assertIn("LinkedIn", message)
        self.assertIn("HTTP 429", message)
        self.assertEqual(client.emit.call_args.args[2]["failure_type"], "rate_limited")

    async def test_403_and_verification_pages_start_an_access_cooldown(self):
        for response in (httpx.Response(403), httpx.Response(200, text="<title>Just a moment...</title>")):
            self.policy = RequestPolicy(now=self.clock.now, sleep=self.clock.sleep)
            handler = AsyncMock(return_value=response)
            client = self.client(handler)
            with self.assertRaises(PortalUnavailable) as caught:
                await client.get("https://www.jobleads.com/in/jobs")
            self.assertEqual(caught.exception.failure_type, "access_denied")
            self.assertEqual(caught.exception.until, self.clock.now() + timedelta(hours=1))

    async def test_cache_reuses_success_but_keeps_different_queries_separate(self):
        handler = AsyncMock(return_value=httpx.Response(200, json={"hits": []}))
        client = self.client(handler)
        await client.get("https://hn.algolia.com/api", params={"query": "Python"})
        await client.get("https://hn.algolia.com/api", params={"query": "Python"})
        await client.get("https://hn.algolia.com/api", params={"query": "AWS"})
        self.assertEqual(handler.await_count, 2)

    async def test_cancellation_releases_the_request_lease(self):
        entered = asyncio.Event()

        async def handler(request):
            entered.set()
            await asyncio.Event().wait()

        client = self.client(handler)
        task = asyncio.create_task(client.get("https://www.linkedin.com/search"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertIsNone(self.policy.local["linkedin.com"].owner)

    async def test_one_host_is_serialized_and_starts_are_spaced(self):
        active = 0
        most_active = 0
        starts = []

        async def handler(request):
            nonlocal active, most_active
            active += 1
            most_active = max(most_active, active)
            starts.append(time.monotonic())
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(200, text="OK")

        with patch.object(settings, "portal_sensitive_request_interval_seconds", 0.03):
            client = PortalHTTP(policy=RequestPolicy(), transport=httpx.MockTransport(handler))
            await asyncio.gather(*(client.get(f"https://www.linkedin.com/search/{index}") for index in range(3)))
        self.assertEqual(most_active, 1)
        self.assertTrue(all(second - first >= 0.025 for first, second in zip(starts, starts[1:])))

    def test_access_blocks_are_not_immediately_retried_as_pipeline_failures(self):
        with self.assertRaises(ValueError):
            raise_if_all_portals_failed({"linkedin": {"status": "failed", "failure_type": "rate_limited"}})
        with self.assertRaises(RuntimeError):
            raise_if_all_portals_failed({"linkedin": {"status": "failed"}})
        raise_if_all_portals_failed({"linkedin": {"status": "failed"}, "remoteok": {"status": "succeeded"}})

    async def test_blocked_portal_skips_combinations_but_other_portals_continue(self):
        requests = []

        def handler(request):
            requests.append(request.url.host)
            if request.url.host == "www.linkedin.com":
                return httpx.Response(429)
            return httpx.Response(200, json=[{"position": "Python AWS Engineer", "description": "Python AWS", "url": "https://example.org/job"}])

        agent = SearchAgent()
        agent.http = self.client(handler)
        agent.http.emit = agent.emit
        with patch("agents.base.BaseAgent.emit", new=AsyncMock()):
            jobs = await agent.run(["Python", "AWS"], ["Remote", "Dubai"], ["linkedin", "remoteok"])
        self.assertEqual(requests.count("www.linkedin.com"), 1)
        self.assertEqual(requests.count("remoteok.com"), 1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(agent.portal_reports["linkedin"]["skipped_searches"], 3)
        self.assertEqual(agent.portal_reports["linkedin"]["failure_type"], "rate_limited")
        self.assertEqual(agent.portal_reports["remoteok"]["status"], "succeeded")

    async def test_nested_jobleads_agents_share_the_parent_cooldown(self):
        handler = AsyncMock(return_value=httpx.Response(403))
        agent = SearchAgent()
        agent.http = self.client(handler)
        agent.http.emit = agent.emit
        with patch("agents.base.BaseAgent.emit", new=AsyncMock()):
            await agent.run(["Python", "AWS"], ["Germany", "Singapore"], ["jobleads"])
        self.assertEqual(handler.await_count, 1)
        self.assertEqual(agent.portal_reports["jobleads"]["skipped_searches"], 3)

    async def test_jobs_found_before_a_later_page_is_limited_are_kept(self):
        def handler(request):
            if request.url.params.get("start") == "0":
                return httpx.Response(200, text='<li><a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/123"></a><h3 class="base-search-card__title">Python Engineer</h3></li>')
            return httpx.Response(429)

        agent = SearchAgent()
        agent.http = self.client(handler)
        agent.http.emit = agent.emit
        with patch("agents.base.BaseAgent.emit", new=AsyncMock()):
            jobs = await agent.run(["Python"], ["Berlin", "Dubai"], ["linkedin"], linkedin_pages=2, max_results=30)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(agent.portal_reports["linkedin"]["status"], "partial")
        self.assertEqual(agent.portal_reports["linkedin"]["skipped_searches"], 1)

    async def test_rss_and_hackernews_feeds_are_reused_across_searches(self):
        requests = []

        def handler(request):
            requests.append(str(request.url))
            if request.url.host == "weworkremotely.com":
                return httpx.Response(200, text='<rss><channel><item><title>Example: Python AWS Engineer</title><description>Python AWS</description><link>https://example.org/rss-job</link></item></channel></rss>')
            if request.url.params.get("tags") == "ask_hn,who_is_hiring":
                return httpx.Response(200, json={"hits": [{"objectID": "1"}]})
            return httpx.Response(200, json={"hits": [{"objectID": "2", "comment_text": "Example | Python AWS Engineer"}]})

        agent = SearchAgent()
        agent.http = self.client(handler)
        with patch("agents.base.BaseAgent.emit", new=AsyncMock()):
            await agent.run(["Python", "AWS"], ["Remote", "Dubai"], ["weworkremotely", "hackernews"])
        self.assertEqual(sum("weworkremotely" in url for url in requests), 3)
        self.assertEqual(sum("hn.algolia" in url for url in requests), 3)


class PersistentPolicyTests(PortalFixtures, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        postgres_url = os.environ.get("JOBFORGE_TEST_DATABASE_URL")
        self.admin_engine = None
        if postgres_url:
            self.schema = f"portal_test_{uuid.uuid4().hex}"
            self.admin_engine = create_async_engine(postgres_url)
            async with self.admin_engine.begin() as connection:
                await connection.execute(CreateSchema(self.schema))
            self.engine = create_async_engine(postgres_url, connect_args={"server_settings": {"search_path": self.schema}})
        else:
            self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.directory.name}/policy.db")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        patcher = patch.object(database, "AsyncSessionLocal", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)
        async with self.engine.begin() as connection:
            await connection.run_sync(PortalRequestState.__table__.create)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if self.admin_engine:
            async with self.admin_engine.begin() as connection:
                await connection.execute(DropSchema(self.schema, cascade=True))
            await self.admin_engine.dispose()
        self.directory.cleanup()

    async def test_new_client_obeys_saved_cooldown_and_can_retry_after_expiry(self):
        first = self.client(lambda request: httpx.Response(429, headers={"Retry-After": "120"}), persistent=True)
        with self.assertRaises(PortalUnavailable):
            await first.get("https://www.linkedin.com/search")
        handler = AsyncMock(return_value=httpx.Response(200, text="OK"))
        second = self.client(handler, persistent=True)
        with self.assertRaises(PortalUnavailable):
            await second.get("https://www.linkedin.com/search")
        handler.assert_not_awaited()
        self.clock.value += timedelta(seconds=121)
        third = self.client(handler, persistent=True)
        self.assertEqual((await third.get("https://www.linkedin.com/search")).status_code, 200)
        handler.assert_awaited_once()

    async def test_an_obsolete_worker_cannot_release_a_new_workers_lease(self):
        first = RequestPolicy(persistent=True, now=self.clock.now, sleep=self.clock.sleep)
        owner = await first.reserve("linkedin.com", "LinkedIn")
        self.clock.value += timedelta(seconds=61)
        second = RequestPolicy(persistent=True, now=self.clock.now, sleep=self.clock.sleep)
        new_owner = await second.reserve("linkedin.com", "LinkedIn")
        await first.release("linkedin.com", owner)
        async with self.sessions() as db:
            state = await db.get(PortalRequestState, "linkedin.com")
            self.assertEqual(state.owner, new_owner)
        await second.release("linkedin.com", new_owner)

    async def test_separate_clients_cannot_fetch_the_same_host_concurrently(self):
        active = 0
        most_active = 0

        async def handler(request):
            nonlocal active, most_active
            active += 1
            most_active = max(most_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return httpx.Response(200, text="OK")

        with patch.object(settings, "portal_sensitive_request_interval_seconds", 0.01):
            clients = [PortalHTTP(policy=RequestPolicy(persistent=True), transport=httpx.MockTransport(handler)) for _ in range(3)]
            await asyncio.gather(*(client.get(f"https://www.linkedin.com/search/{index}") for index, client in enumerate(clients)))
        self.assertEqual(most_active, 1)

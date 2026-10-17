import unittest
from unittest.mock import AsyncMock, patch

from bs4 import BeautifulSoup

from agents.jobleads import JobLeadsAgent, _resolve_location
from agents.search import SearchAgent
from api.routes.search_config import SearchConfigCreate


def card(work_setting="Remote", href="/in/job/software-engineer--india--e123"):
    return f'''
    <div data-testid="search-job-card">
      <a data-testid="search-job-card-link" href="{href}?tracking=1">Engineer</a>
      <h2>Software Engineer</h2>
      <p data-testid="search-job-card-company">
        <span data-testid="search-job-card-company-name">Example Ltd</span>
        <span>&bull; Bengaluru</span>
      </p>
      <span data-testid="job-card-chip-work-setting">{work_setting}</span>
      <span data-testid="job-card-chip-salary">INR 600,000 - 900,000</span>
      <span data-testid="job-card-date">2 hours ago</span>
    </div>'''


class JobLeadsTests(unittest.IsolatedAsyncioTestCase):
    def test_country_names_and_codes_resolve_markets(self):
        for location, country in [("Germany", "de"), (" Singapore ", "sg"),
                                  ("INDIA", "in"), ("DE", "de"), ("SG", "sg"),
                                  ("UK", "gb"), ("United   States", "us")]:
            with self.subTest(location=location):
                self.assertEqual(_resolve_location(location), (country, ""))

    def test_city_and_remote_use_fallback(self):
        with patch("agents.jobleads.settings.jobleads_country", "de"):
            self.assertEqual(_resolve_location("Berlin"), ("de", "Berlin"))
            self.assertEqual(_resolve_location("Remote"), ("de", "Remote"))

    async def test_country_overrides_fallback_without_city_filter(self):
        for location, country in [("Germany", "de"), ("Singapore", "sg")]:
            with self.subTest(location=location):
                agent = JobLeadsAgent()
                agent.emit = AsyncMock()
                with patch("agents.jobleads.settings.jobleads_country", "in"):
                    with patch.object(SearchAgent, "_fetch", new=AsyncMock(return_value="<html></html>")) as fetch:
                        await agent.run("software engineer", location, remote_only=True)
                self.assertEqual(fetch.call_args.args[0], f"https://www.jobleads.com/{country}/jobs/q/software%20engineer")
                self.assertEqual(fetch.call_args.kwargs["params"]["filter_by_remote"], "remote")

    async def test_searches_multiple_ui_countries_in_one_run(self):
        agent = SearchAgent()
        agent.emit = AsyncMock()
        requested_urls = []

        async def fetch(fetcher, url, params=None):
            requested_urls.append(url)
            country = url.split("/")[3]
            return card(href=f"/{country}/job/engineer--e123")

        with patch.object(SearchAgent, "_fetch", new=fetch):
            with patch.object(JobLeadsAgent, "emit", new=AsyncMock()):
                with patch("agents.search.asyncio.sleep", new=AsyncMock()):
                    jobs = await agent.run(keywords=["engineer"], locations=["Germany", "Singapore"], portals=["jobleads"])
        self.assertEqual(len(jobs), 2)
        self.assertEqual(set(requested_urls), {"https://www.jobleads.com/de/jobs/q/engineer",
                                              "https://www.jobleads.com/sg/jobs/q/engineer"})

    def test_card_fields(self):
        job = JobLeadsAgent._parse_card(BeautifulSoup(card(), "html.parser"))
        self.assertEqual(job["company"], "Example Ltd")
        self.assertEqual(job["location"], "Bengaluru")
        self.assertEqual(job["salary_range"], "INR 600,000 - 900,000")
        self.assertEqual(job["url"], "https://www.jobleads.com/in/job/software-engineer--india--e123")
        self.assertTrue(job["remote"])
        self.assertIsNotNone(job["posted_at"])

    def test_reject_foreign_link(self):
        soup = BeautifulSoup(card(href="https://other.example/in/job/123"), "html.parser")
        self.assertIsNone(JobLeadsAgent._parse_card(soup))

    def test_config_accepts_jobleads(self):
        config = SearchConfigCreate(keywords=["engineer"], portals=["jobleads"])
        self.assertEqual(config.portals, ["jobleads"])

    async def test_remote_filter_limit_and_dedup(self):
        html = card("On-site", "/in/job/onsite--e1") + card() + card() + card(href="/in/job/remote--e2")
        agent = JobLeadsAgent()
        agent.emit = AsyncMock()
        with patch.object(SearchAgent, "_fetch", new=AsyncMock(return_value=html)) as fetch:
            jobs = await agent.run("C++ engineer", "Remote", max_results=1)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["remote"])
        self.assertIn("/q/C%2B%2B%20engineer", fetch.call_args.args[0])
        self.assertNotIn("/l/", fetch.call_args.args[0])
        self.assertEqual(fetch.call_args.kwargs["params"]["filter_by_remote"], "remote")

        with patch.object(SearchAgent, "_fetch", new=AsyncMock(return_value=html)):
            jobs = await agent.run("engineer", "Remote", max_results=10)
        self.assertEqual(len(jobs), 2)

    async def test_repeated_page_stops_pagination(self):
        agent = JobLeadsAgent()
        agent.emit = AsyncMock()
        html = "".join(card(href=f"/in/job/engineer--e{i}") for i in range(25))
        with patch.object(SearchAgent, "_fetch", new=AsyncMock(return_value=html)) as fetch:
            with patch("agents.jobleads.asyncio.sleep", new=AsyncMock()):
                jobs = await agent.run("engineer", "Bengaluru", max_results=100)
        self.assertEqual(len(jobs), 25)
        self.assertEqual(fetch.await_count, 2)

    async def test_posting_age_filter(self):
        agent = JobLeadsAgent()
        agent.emit = AsyncMock()
        with patch.object(SearchAgent, "_fetch", new=AsyncMock(return_value=card().replace("2 hours ago", "10 days ago"))):
            self.assertEqual(await agent.run("engineer", "Remote", posted_within_days=3), [])

    async def test_dispatch_forwards_filters(self):
        with patch.object(JobLeadsAgent, "run", new=AsyncMock(return_value=[])) as run:
            await SearchAgent()._search_one("jobleads", "engineer", "Berlin", True, 20, 1, 3)
        run.assert_awaited_once_with(keyword="engineer", location="Berlin", remote_only=True,
                                     max_results=20, posted_within_days=3)

    async def test_fetch_failure_emits_error(self):
        agent = JobLeadsAgent()
        agent.emit = AsyncMock()
        with patch.object(SearchAgent, "_fetch", new=AsyncMock(return_value=None)):
            self.assertEqual(await agent.run("engineer", "Remote"), [])
        self.assertTrue(any(call.args[0] == "error" for call in agent.emit.await_args_list))


if __name__ == "__main__":
    unittest.main()

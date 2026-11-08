import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx

from agents.docgen import DocGenAgent
from agents.rank import RankAgent
from agents.research import ResearchAgent
from core.job_descriptions import ensure_description, extract_description, plain_text, replace_description
from models.job import Job


LONG_DESCRIPTION = "Responsibilities and requirements. " * 500 + "END REQUIREMENT: Sponsorship available for eligible candidates."


class DescriptionTests(unittest.IsolatedAsyncioTestCase):
    def job(self, **values):
        return Job(id=1, title="Engineer", company="Example", portal="linkedin", url="https://example.org/job", **values)

    def test_extracts_entire_structured_description_before_removing_scripts(self):
        import json
        html = '<main>Navigation</main><script type="application/ld+json">' + json.dumps({"@graph": [{"@type": "JobPosting", "description": f"<p>{LONG_DESCRIPTION}</p>"}]}) + '</script>'
        result = extract_description(html)
        self.assertEqual(result, LONG_DESCRIPTION)

    def test_prefers_job_section_over_navigation_and_preserves_tail(self):
        html = f'<main>Unrelated content<div class="show-more-less-html__markup"><p>{LONG_DESCRIPTION}</p></div><footer>Footer</footer></main>'
        self.assertEqual(extract_description(html), LONG_DESCRIPTION)
        self.assertEqual(plain_text("<p>First</p><p>Second</p><script>tracking()</script>"), "First\nSecond")

    def test_access_verification_does_not_become_a_job_description(self):
        with self.assertRaises(ValueError):
            extract_description("<title>Just a moment...</title><body>Verify browser</body>")

    async def test_legacy_snippet_over_200_characters_is_upgraded_and_cached(self):
        job = self.job(description="Old snippet. " * 40, fit_score=90, researched_at=datetime.utcnow(), status="ranked")
        emit = AsyncMock()
        fetch = AsyncMock(return_value=LONG_DESCRIPTION)
        await ensure_description(job, emit, fetch)
        await ensure_description(job, emit, fetch)
        fetch.assert_awaited_once_with(job.url)
        self.assertEqual(job.description, LONG_DESCRIPTION)
        self.assertEqual(job.description_source, "listing")
        self.assertIsNone(job.fit_score)
        self.assertIsNone(job.researched_at)
        self.assertEqual(job.status, "new")

    async def test_failed_fetch_keeps_existing_text_and_records_warning(self):
        job = self.job(description=LONG_DESCRIPTION)
        fetch = AsyncMock(side_effect=httpx.ConnectError("Connection unavailable"))
        await ensure_description(job, AsyncMock(), fetch)
        await ensure_description(job, AsyncMock(), fetch)
        self.assertEqual(job.description, LONG_DESCRIPTION)
        self.assertIn("Connection unavailable", job.description_error)
        fetch.assert_awaited_once()

    async def test_manual_description_is_never_fetched_or_truncated(self):
        job = self.job(description=LONG_DESCRIPTION)
        job.portal = "manual"
        fetch = AsyncMock()
        self.assertEqual(await ensure_description(job, AsyncMock(), fetch), LONG_DESCRIPTION)
        fetch.assert_not_awaited()

    def test_shorter_response_cannot_overwrite_longer_description(self):
        job = self.job(description=LONG_DESCRIPTION, fit_score=85)
        self.assertFalse(replace_description(job, "Short response", "listing"))
        self.assertEqual(job.description, LONG_DESCRIPTION)
        self.assertEqual(job.fit_score, 85)

    async def test_rank_prompt_contains_requirements_at_end_of_description(self):
        job = self.job(description=LONG_DESCRIPTION)
        job.portal = "manual"
        agent = RankAgent()
        agent.chat_json = AsyncMock(return_value={"overall": 80})
        await agent._score_job(job, "Candidate profile")
        self.assertIn(LONG_DESCRIPTION, agent.chat_json.call_args.args[0][1]["content"])

    async def test_research_prompt_contains_entire_description(self):
        agent = ResearchAgent()
        agent.chat_json = AsyncMock(return_value={"fit_score": 80, "tech_score": 80, "exp_score": 80, "location_score": 80, "growth_score": 80, "strengths": [], "gaps": [], "fit_summary": "Fit", "talking_points": []})
        await agent._analyse(self.job(description=LONG_DESCRIPTION), LONG_DESCRIPTION, {})
        self.assertIn(LONG_DESCRIPTION, agent.chat_json.call_args.args[0][1]["content"])

    def test_document_context_contains_entire_description(self):
        context = DocGenAgent._build_job_context(self.job(description=LONG_DESCRIPTION))
        self.assertIn(LONG_DESCRIPTION, context)

    async def test_remoteok_feed_retains_full_description(self):
        from agents.search import SearchAgent
        response = httpx.Response(200, json=[{"position": "Python Engineer", "description": f"<p>{LONG_DESCRIPTION}</p>", "url": "https://example.org/job"}], request=httpx.Request("GET", "https://remoteok.com/api"))
        with patch("agents.search.httpx.AsyncClient") as client:
            client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
            jobs = await SearchAgent()._search_remoteok("Python", "Remote")
        self.assertEqual(jobs[0]["description"], LONG_DESCRIPTION)

    async def test_rss_description_retains_tail(self):
        from agents.search import SearchAgent
        agent = SearchAgent()
        html = f'<rss><channel><item><title>Example: Python Engineer</title><link>https://example.org/job</link><description>{LONG_DESCRIPTION}</description></item></channel></rss>'
        with patch.object(agent, "_fetch", new=AsyncMock(return_value=html)), patch.object(agent, "_WWR_FEEDS", ["https://example.org/feed"]):
            jobs = await agent._search_weworkremotely("Python")
        self.assertEqual(jobs[0]["description"], LONG_DESCRIPTION)

    async def test_hackernews_description_retains_tail(self):
        from agents.search import SearchAgent
        responses = [httpx.Response(200, json={"hits": [{"objectID": "1"}]}), httpx.Response(200, json={"hits": [{"objectID": "2", "comment_text": f"Example | Python Engineer<p>{LONG_DESCRIPTION}</p>"}]})]
        with patch("agents.search.httpx.AsyncClient") as client:
            client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=responses)
            jobs = await SearchAgent()._search_hackernews("Python", False)
        self.assertIn(LONG_DESCRIPTION, jobs[0]["description"])

"""
JobForge — Search Agent
Searches multiple job portals for listings matching the user's profile.

Portals supported:
  - LinkedIn  (public guest API, no auth)
  - Indeed    (public scraping)
  - Mock      (generates fake data for local testing without internet)

Rate limiting and deduplication are handled here.
Results are stored in the DB by the caller (jobs route).
"""

import asyncio
import random
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from core.config import settings
from agents.base import BaseAgent
import structlog

log = structlog.get_logger()

# Rotate user agents to reduce bot detection
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

EXTRACT_PROMPT = """Extract structured job info from this job listing text.
Return ONLY valid JSON — no markdown, no explanation:
{
  "title": "exact job title",
  "company": "company name",
  "location": "city, country or Remote",
  "remote": true or false,
  "salary_range": "e.g. $80k-$120k or null",
  "job_type": "full-time | part-time | contract | internship",
  "description": "first 400 characters of job description",
  "posted_at": "YYYY-MM-DD or null"
}"""


class SearchAgent(BaseAgent):
    name = "search"
    model = settings.llm_model_fast  # fast model — many parallel calls

    async def run(
        self,
        keywords: list[str],
        locations: list[str],
        portals: list[str],
        remote_only: bool = False,
        posted_within_days: int = 7,
    ) -> list[dict]:
        """
        Search all configured portals in parallel for each keyword × location combo.

        Returns:
            List of job dicts ready to be stored (deduplicated by URL).
        """
        await self.emit(
            "started",
            f"Searching {len(portals)} portal(s) — {len(keywords)} keyword(s) × {len(locations)} location(s)...",
        )

        # Build all search combos
        combos = [
            (portal, keyword, location)
            for portal in portals
            for keyword in keywords
            for location in locations
        ]

        await self.emit("thinking", f"Running {len(combos)} searches in parallel...")

        # Run all combos concurrently (with a semaphore to avoid hammering portals)
        sem = asyncio.Semaphore(4)  # max 4 concurrent requests

        async def bounded_search(portal, keyword, location):
            async with sem:
                await asyncio.sleep(random.uniform(0.5, 1.5))  # polite delay
                return await self._search_one(portal, keyword, location, remote_only)

        results = await asyncio.gather(
            *[bounded_search(p, k, l) for p, k, l in combos],
            return_exceptions=True,
        )

        # Flatten + deduplicate by URL
        seen_urls: set[str] = set()
        all_jobs: list[dict] = []
        for batch in results:
            if isinstance(batch, Exception):
                log.warning("search.batch_error", error=str(batch))
                continue
            for job in batch:
                url = job.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_jobs.append(job)

        await self.emit(
            "done",
            f"Found {len(all_jobs)} unique jobs across {len(portals)} portal(s).",
            {"count": len(all_jobs), "portals": portals},
        )
        return all_jobs

    # ─── Portal dispatcher ────────────────────────────────────────────────

    async def _search_one(
        self, portal: str, keyword: str, location: str, remote_only: bool
    ) -> list[dict]:
        if portal == "linkedin":
            return await self._search_linkedin(keyword, location, remote_only)
        elif portal == "indeed":
            return await self._search_indeed(keyword, location, remote_only)
        elif portal == "mock":
            return self._mock_jobs(keyword, location)
        else:
            log.warning("search.unknown_portal", portal=portal)
            return []

    # ─── LinkedIn ─────────────────────────────────────────────────────────

    async def _search_linkedin(
        self, keyword: str, location: str, remote_only: bool
    ) -> list[dict]:
        """LinkedIn public guest jobs API — no auth required."""
        params = {
            "keywords": keyword,
            "location": location,
            "f_TPR": "r604800",   # last 7 days
            "start": "0",
        }
        if remote_only:
            params["f_WT"] = "2"  # remote filter

        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

        raw_cards = await self._fetch_html(url, params=params)
        if not raw_cards:
            return []

        soup = BeautifulSoup(raw_cards, "html.parser")
        cards = soup.find_all("li")
        log.info("search.linkedin_cards", keyword=keyword, count=len(cards))

        jobs = []
        for card in cards[:15]:  # cap per search combo
            job = self._parse_linkedin_card(card, keyword)
            if job:
                jobs.append(job)
        return jobs

    def _parse_linkedin_card(self, card, keyword: str) -> dict | None:
        try:
            link = card.find("a", class_="base-card__full-link")
            if not link:
                return None
            url = link["href"].split("?")[0]

            title_el = card.find("h3", class_="base-search-card__title")
            company_el = card.find("h4", class_="base-search-card__subtitle")
            location_el = card.find("span", class_="job-search-card__location")
            date_el = card.find("time")

            posted_at = None
            if date_el and date_el.get("datetime"):
                try:
                    posted_at = datetime.strptime(date_el["datetime"][:10], "%Y-%m-%d")
                except Exception:
                    pass

            return {
                "url": url,
                "title": title_el.get_text(strip=True) if title_el else keyword,
                "company": company_el.get_text(strip=True) if company_el else "Unknown",
                "location": location_el.get_text(strip=True) if location_el else "",
                "portal": "linkedin",
                "remote": "remote" in (location_el.get_text(strip=True) if location_el else "").lower(),
                "posted_at": posted_at,
                "status": "new",
            }
        except Exception as e:
            log.debug("search.linkedin_parse_error", error=str(e))
            return None

    # ─── Indeed ───────────────────────────────────────────────────────────

    async def _search_indeed(
        self, keyword: str, location: str, remote_only: bool
    ) -> list[dict]:
        """Indeed public job search scraper."""
        params = {
            "q": keyword,
            "l": "" if remote_only else location,
            "sort": "date",
            "fromage": "7",  # last 7 days
        }
        if remote_only:
            params["remotejob"] = "032b3046-06a3-4876-8dfd-474eb5e7ed11"

        url = "https://www.indeed.com/jobs"

        raw_html = await self._fetch_html(url, params=params)
        if not raw_html:
            return []

        soup = BeautifulSoup(raw_html, "html.parser")

        # Indeed job cards
        cards = soup.find_all("div", class_="job_seen_beacon")
        if not cards:
            # Try alternate class
            cards = soup.find_all("div", attrs={"data-testid": "slider_item"})

        log.info("search.indeed_cards", keyword=keyword, count=len(cards))

        jobs = []
        for card in cards[:15]:
            job = self._parse_indeed_card(card, keyword, location)
            if job:
                jobs.append(job)
        return jobs

    def _parse_indeed_card(self, card, keyword: str, location: str) -> dict | None:
        try:
            # Job link
            link = card.find("a", class_="jcs-JobTitle") or card.find("a", href=True)
            if not link:
                return None

            href = link.get("href", "")
            if href.startswith("/"):
                url = f"https://www.indeed.com{href}"
            else:
                url = href

            title = link.get_text(strip=True) if link else keyword

            company_el = (
                card.find("span", attrs={"data-testid": "company-name"})
                or card.find("span", class_="companyName")
            )
            location_el = (
                card.find("div", attrs={"data-testid": "text-location"})
                or card.find("div", class_="companyLocation")
            )
            salary_el = (
                card.find("div", attrs={"data-testid": "attribute_snippet_testid"})
                or card.find("span", class_="salary-snippet")
            )

            loc_text = location_el.get_text(strip=True) if location_el else location

            return {
                "url": url,
                "title": title,
                "company": company_el.get_text(strip=True) if company_el else "Unknown",
                "location": loc_text,
                "portal": "indeed",
                "remote": "remote" in loc_text.lower(),
                "salary_range": salary_el.get_text(strip=True) if salary_el else None,
                "posted_at": None,
                "status": "new",
            }
        except Exception as e:
            log.debug("search.indeed_parse_error", error=str(e))
            return None

    # ─── Mock (for local testing without internet) ─────────────────────────

    def _mock_jobs(self, keyword: str, location: str) -> list[dict]:
        """
        Returns realistic fake jobs for testing the pipeline
        without hitting real portals.
        Enable by adding "mock" to portals in SearchConfig.
        """
        companies = ["Stripe", "Notion", "Linear", "Vercel", "Supabase", "Planetscale"]
        roles = [keyword, f"Senior {keyword}", f"Staff {keyword}", f"Lead {keyword}"]

        return [
            {
                "url": f"https://mock.jobforge.dev/jobs/{i}-{keyword.lower().replace(' ','-')}",
                "title": random.choice(roles),
                "company": random.choice(companies),
                "location": location,
                "portal": "mock",
                "remote": True,
                "salary_range": f"${random.randint(80,150)}k–${random.randint(150,220)}k",
                "job_type": "full-time",
                "description": f"We are looking for a {keyword} to join our team. "
                               f"You will work on exciting distributed systems challenges.",
                "posted_at": datetime.utcnow() - timedelta(days=random.randint(0, 5)),
                "status": "new",
            }
            for i in range(1, 6)
        ]

    # ─── HTTP helper ──────────────────────────────────────────────────────

    async def _fetch_html(self, url: str, params: dict | None = None) -> str | None:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    return resp.text
                log.warning("search.http_error", url=url, status=resp.status_code)
                return None
        except Exception as e:
            log.warning("search.fetch_failed", url=url, error=str(e))
            return None

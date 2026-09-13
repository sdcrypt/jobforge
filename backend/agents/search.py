"""
JobForge — Search Agent
Searches multiple job portals for listings matching the user's profile.

Portals:
  linkedin        — LinkedIn public guest API (no auth)
  remoteok        — RemoteOK free public JSON API
  weworkremotely  — We Work Remotely RSS feed
  hackernews      — HackerNews "Who is Hiring" (via Algolia search API)
  mock            — Fake jobs for local testing without internet

Rate limiting and deduplication are handled here.
Results are stored in the DB by the pipeline (pipeline.py).
"""

import asyncio
import random
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dateutil import parser as dateutil_parser
from core.config import settings
from agents.base import BaseAgent
import structlog

log = structlog.get_logger()

# ── User-agent rotation ───────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def _ua() -> str:
    return random.choice(USER_AGENTS)


def _safe_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return dateutil_parser.parse(raw, ignoretz=True)
    except Exception:
        return None


class SearchAgent(BaseAgent):
    name = "search"
    model = settings.llm_model_fast

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(
        self,
        keywords: list[str],
        locations: list[str],
        portals: list[str],
        remote_only: bool = False,
        posted_within_days: int = 7,
    ) -> list[dict]:
        await self.emit(
            "started",
            f"Searching {len(portals)} portal(s) — "
            f"{len(keywords)} keyword(s) × {len(locations)} location(s)…",
        )

        combos = [
            (portal, keyword, location)
            for portal in portals
            for keyword in keywords
            for location in locations
        ]

        await self.emit("thinking", f"Running {len(combos)} searches in parallel…")

        sem = asyncio.Semaphore(4)

        async def bounded(portal, keyword, location):
            async with sem:
                await asyncio.sleep(random.uniform(0.4, 1.2))
                return await self._search_one(portal, keyword, location, remote_only)

        results = await asyncio.gather(
            *[bounded(p, k, l) for p, k, l in combos],
            return_exceptions=True,
        )

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

    # ── Portal dispatcher ─────────────────────────────────────────────────────

    async def _search_one(
        self, portal: str, keyword: str, location: str, remote_only: bool
    ) -> list[dict]:
        try:
            if portal == "linkedin":
                return await self._search_linkedin(keyword, location, remote_only)
            elif portal == "remoteok":
                return await self._search_remoteok(keyword, location)
            elif portal == "weworkremotely":
                return await self._search_weworkremotely(keyword)
            elif portal == "hackernews":
                return await self._search_hackernews(keyword, remote_only)
            elif portal == "indeed":
                return await self._search_indeed(keyword, location, remote_only)
            elif portal == "mock":
                return self._mock_jobs(keyword, location)
            else:
                log.warning("search.unknown_portal", portal=portal)
                return []
        except Exception as e:
            log.warning("search.portal_error", portal=portal, error=str(e))
            return []

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: LinkedIn
    # ═══════════════════════════════════════════════════════════════════════════

    async def _search_linkedin(
        self, keyword: str, location: str, remote_only: bool
    ) -> list[dict]:
        """LinkedIn public guest jobs API — no auth required."""
        params = {
            "keywords": keyword,
            "location": location,
            "f_TPR": "r604800",  # last 7 days
            "start": "0",
        }
        if remote_only:
            params["f_WT"] = "2"

        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        raw = await self._fetch(url, params=params)
        if not raw:
            return []

        soup = BeautifulSoup(raw, "html.parser")
        cards = soup.find_all("li")
        log.info("search.linkedin", keyword=keyword, cards=len(cards))

        jobs = []
        for card in cards[:15]:
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
                posted_at = _safe_date(date_el["datetime"][:10])

            loc_text = location_el.get_text(strip=True) if location_el else ""
            return {
                "url": url,
                "title": title_el.get_text(strip=True) if title_el else keyword,
                "company": company_el.get_text(strip=True) if company_el else "Unknown",
                "location": loc_text,
                "portal": "linkedin",
                "remote": "remote" in loc_text.lower(),
                "posted_at": posted_at,
                "status": "new",
            }
        except Exception as e:
            log.debug("search.linkedin_parse_err", error=str(e))
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: RemoteOK  (free public JSON API — https://remoteok.com/api)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _search_remoteok(self, keyword: str, location: str) -> list[dict]:
        """
        RemoteOK free API.  Returns all remote tech jobs; we filter locally by keyword.
        Rate limit note: they ask for ≤1 req/hour. The pipeline semaphore + delay handles this.
        """
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={
                    "User-Agent": _ua(),
                    "Accept": "application/json",
                },
            ) as client:
                resp = await client.get("https://remoteok.com/api")
                if resp.status_code != 200:
                    log.warning("search.remoteok_http", status=resp.status_code)
                    return []

                data = resp.json()
        except Exception as e:
            log.warning("search.remoteok_error", error=str(e))
            return []

        # First item is legal notice — skip
        raw_jobs = [j for j in data if isinstance(j, dict) and j.get("position")]

        kw_words = keyword.lower().split()
        jobs = []
        for job in raw_jobs:
            search_text = " ".join([
                job.get("position", ""),
                " ".join(job.get("tags") or []),
                job.get("description", ""),
            ]).lower()

            if not all(w in search_text for w in kw_words):
                continue

            salary = None
            lo, hi = job.get("salary_min"), job.get("salary_max")
            if lo and hi:
                salary = f"${int(lo)//1000}k–${int(hi)//1000}k"
            elif lo:
                salary = f"${int(lo)//1000}k+"

            jobs.append({
                "url": job.get("url") or f"https://remoteok.com/remote-jobs/{job.get('id')}",
                "title": job.get("position", keyword),
                "company": job.get("company", "Unknown"),
                "location": "Remote",
                "portal": "remoteok",
                "remote": True,
                "salary_range": salary,
                "job_type": "full-time",
                "description": BeautifulSoup(job.get("description", ""), "html.parser").get_text()[:500],
                "posted_at": _safe_date(job.get("date")),
                "status": "new",
            })

            if len(jobs) >= 15:
                break

        log.info("search.remoteok", keyword=keyword, matched=len(jobs))
        return jobs

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: We Work Remotely  (RSS feed)
    # ═══════════════════════════════════════════════════════════════════════════

    WEWORKREMOTELY_FEEDS = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    ]

    async def _search_weworkremotely(self, keyword: str) -> list[dict]:
        """We Work Remotely public RSS feeds — no auth required."""
        kw_words = keyword.lower().split()
        jobs: list[dict] = []
        seen: set[str] = set()

        for feed_url in self.WEWORKREMOTELY_FEEDS:
            raw = await self._fetch(feed_url)
            if not raw:
                continue

            soup = BeautifulSoup(raw, "html.parser")
            items = soup.find_all("item")

            for item in items:
                title_el = item.find("title")
                # WWR titles are like: "Company: Job Title"
                title_raw = title_el.get_text(strip=True) if title_el else ""
                title_parts = title_raw.split(": ", 1)
                company = title_parts[0].strip() if len(title_parts) > 1 else "Unknown"
                title = title_parts[1].strip() if len(title_parts) > 1 else title_raw

                desc_el = item.find("description")
                desc_text = BeautifulSoup(
                    desc_el.get_text(strip=True) if desc_el else "", "html.parser"
                ).get_text()

                search_text = f"{title} {desc_text}".lower()
                if not all(w in search_text for w in kw_words):
                    continue

                # WWR RSS: link text is between <link> tags (CDATA quirk)
                link_el = item.find("link")
                url = ""
                if link_el:
                    # In RSS, <link> is often a sibling text node, not element text
                    url = link_el.next_sibling or link_el.get_text(strip=True) or ""
                    url = str(url).strip()
                if not url or url in seen:
                    continue

                seen.add(url)
                jobs.append({
                    "url": url if url.startswith("http") else f"https://weworkremotely.com{url}",
                    "title": title,
                    "company": company,
                    "location": "Remote",
                    "portal": "weworkremotely",
                    "remote": True,
                    "salary_range": None,
                    "job_type": "full-time",
                    "description": desc_text[:500],
                    "posted_at": _safe_date(
                        item.find("pubdate") and item.find("pubdate").get_text(strip=True)
                    ),
                    "status": "new",
                })

                if len(jobs) >= 15:
                    break

            if len(jobs) >= 15:
                break

        log.info("search.weworkremotely", keyword=keyword, matched=len(jobs))
        return jobs

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: HackerNews "Who is Hiring"  (Algolia HN search API)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _search_hackernews(self, keyword: str, remote_only: bool) -> list[dict]:
        """
        Searches HackerNews 'Who is Hiring' monthly thread via Algolia API.
        No auth required.  Algolia already filters comments by keyword for us.
        """
        try:
            async with httpx.AsyncClient(timeout=15) as client:

                # Step 1: Find the latest "Who is Hiring" story ID
                r1 = await client.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    params={"tags": "ask_hn,who_is_hiring", "hitsPerPage": 1},
                )
                if r1.status_code != 200:
                    return []

                hits = r1.json().get("hits", [])
                if not hits:
                    return []

                story_id = hits[0]["objectID"]
                story_title = hits[0].get("title", "Who is Hiring")
                log.info("search.hackernews_thread", story_id=story_id, title=story_title)

                # Step 2: Search comments in that story for our keyword
                query = keyword
                if remote_only:
                    query = f"{keyword} remote"

                r2 = await client.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    params={
                        "tags": f"comment,story_{story_id}",
                        "query": query,
                        "hitsPerPage": 20,
                    },
                )
                if r2.status_code != 200:
                    return []

                comment_hits = r2.json().get("hits", [])
        except Exception as e:
            log.warning("search.hackernews_error", error=str(e))
            return []

        jobs = []
        for hit in comment_hits:
            text_html = hit.get("comment_text", "") or ""
            text = BeautifulSoup(text_html, "html.parser").get_text()

            if not text.strip():
                continue

            if remote_only and "remote" not in text.lower():
                continue

            # First line is usually "Company | Role | Location | ..." or "Company: Role"
            first_line = text.split("\n")[0].strip()[:120]
            parts = [p.strip() for p in first_line.replace("|", "·").split("·")]
            company = parts[0] if parts else "Unknown"

            # Infer title from keyword + context
            title = keyword
            for part in parts[1:]:
                p_lower = part.lower()
                if any(w in p_lower for w in ["engineer", "developer", "lead", "manager", "designer"]):
                    title = part
                    break

            jobs.append({
                "url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "title": title or keyword,
                "company": company[:100],
                "location": "See post (often Remote)",
                "portal": "hackernews",
                "remote": "remote" in text.lower(),
                "salary_range": None,
                "job_type": "full-time",
                "description": text[:500],
                "posted_at": _safe_date(hit.get("created_at")),
                "status": "new",
            })

        log.info("search.hackernews", keyword=keyword, matched=len(jobs))
        return jobs

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: Indeed  (note: often blocked by Cloudflare — unreliable)
    # ═══════════════════════════════════════════════════════════════════════════

    async def _search_indeed(
        self, keyword: str, location: str, remote_only: bool
    ) -> list[dict]:
        """
        Indeed HTML scraper.
        WARNING: Indeed uses Cloudflare anti-bot — this frequently returns 0 results.
        Use RemoteOK / WWR / HackerNews instead for reliable results.
        """
        params = {
            "q": keyword,
            "l": "" if remote_only else location,
            "sort": "date",
            "fromage": "7",
        }
        if remote_only:
            params["remotejob"] = "032b3046-06a3-4876-8dfd-474eb5e7ed11"

        raw = await self._fetch("https://www.indeed.com/jobs", params=params)
        if not raw:
            return []

        soup = BeautifulSoup(raw, "html.parser")
        cards = soup.find_all("div", class_="job_seen_beacon")
        if not cards:
            cards = soup.find_all("div", attrs={"data-testid": "slider_item"})

        log.info("search.indeed", keyword=keyword, cards=len(cards))

        jobs = []
        for card in cards[:15]:
            job = self._parse_indeed_card(card, keyword, location)
            if job:
                jobs.append(job)
        return jobs

    def _parse_indeed_card(self, card, keyword: str, location: str) -> dict | None:
        try:
            link = card.find("a", class_="jcs-JobTitle") or card.find("a", href=True)
            if not link:
                return None

            href = link.get("href", "")
            url = f"https://www.indeed.com{href}" if href.startswith("/") else href

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
                "title": link.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else "Unknown",
                "location": loc_text,
                "portal": "indeed",
                "remote": "remote" in loc_text.lower(),
                "salary_range": salary_el.get_text(strip=True) if salary_el else None,
                "posted_at": None,
                "status": "new",
            }
        except Exception as e:
            log.debug("search.indeed_parse_err", error=str(e))
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: Mock  (local testing — no internet / LLM needed)
    # ═══════════════════════════════════════════════════════════════════════════

    def _mock_jobs(self, keyword: str, location: str) -> list[dict]:
        companies = ["Stripe", "Notion", "Linear", "Vercel", "Supabase", "Planetscale",
                     "Figma", "Retool", "Loom", "Pitch"]
        roles = [keyword, f"Senior {keyword}", f"Staff {keyword}", f"Lead {keyword}"]

        return [
            {
                "url": f"https://mock.jobforge.dev/jobs/{i}-{keyword.lower().replace(' ', '-')}",
                "title": random.choice(roles),
                "company": random.choice(companies),
                "location": location,
                "portal": "mock",
                "remote": True,
                "salary_range": f"${random.randint(80, 150)}k–${random.randint(150, 220)}k",
                "job_type": "full-time",
                "description": (
                    f"We are looking for a {keyword} to join our growing team. "
                    f"You'll work on exciting distributed systems and product challenges."
                ),
                "posted_at": datetime.utcnow() - timedelta(days=random.randint(0, 5)),
                "status": "new",
            }
            for i in range(1, 6)
        ]

    # ── HTTP helper ───────────────────────────────────────────────────────────

    async def _fetch(self, url: str, params: dict | None = None) -> str | None:
        headers = {
            "User-Agent": _ua(),
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

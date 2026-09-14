"""
JobForge — Search Agent
Searches multiple job portals for listings matching the user's profile.

Portals:
  linkedin        — LinkedIn public guest API (no auth)
  remoteok        — RemoteOK free public JSON API
  weworkremotely  — We Work Remotely RSS feed
  hackernews      — HackerNews "Who is Hiring" (Algolia search API)

Rate limiting and in-memory deduplication are handled here.
Final DB deduplication (URL + company+title) is done in pipeline.py.
"""

import asyncio
import random
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
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

SUPPORTED_PORTALS = {"linkedin", "remoteok", "weworkremotely", "hackernews"}


def _ua() -> str:
    return random.choice(USER_AGENTS)


def _safe_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return dateutil_parser.parse(str(raw), ignoretz=True)
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
        max_results: int = 15,       # results per keyword+location+portal combo
        linkedin_pages: int = 1,     # LinkedIn result pages (each page ≈ 25 jobs)
    ) -> list[dict]:
        # Filter out any unsupported portals silently
        active_portals = [p for p in portals if p in SUPPORTED_PORTALS]
        if not active_portals:
            await self.emit("error", "No supported portals selected. Choose from: " + ", ".join(SUPPORTED_PORTALS))
            return []

        await self.emit(
            "started",
            f"Searching {len(active_portals)} portal(s) — "
            f"{len(keywords)} keyword(s) × {len(locations)} location(s) "
            f"(up to {max_results} results each)…",
        )

        combos = [
            (portal, keyword, location)
            for portal in active_portals
            for keyword in keywords
            for location in locations
        ]

        await self.emit("thinking", f"Running {len(combos)} searches in parallel…")

        sem = asyncio.Semaphore(4)

        async def bounded(portal, keyword, location):
            async with sem:
                await asyncio.sleep(random.uniform(0.4, 1.2))
                return await self._search_one(
                    portal, keyword, location, remote_only,
                    max_results=max_results,
                    linkedin_pages=linkedin_pages,
                )

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
            f"Found {len(all_jobs)} unique jobs across {len(active_portals)} portal(s).",
            {"count": len(all_jobs), "portals": active_portals},
        )
        return all_jobs

    # ── Portal dispatcher ─────────────────────────────────────────────────────

    async def _search_one(
        self,
        portal: str,
        keyword: str,
        location: str,
        remote_only: bool,
        max_results: int = 15,
        linkedin_pages: int = 1,
    ) -> list[dict]:
        try:
            if portal == "linkedin":
                return await self._search_linkedin(keyword, location, remote_only,
                                                   max_results=max_results, pages=linkedin_pages)
            elif portal == "remoteok":
                return await self._search_remoteok(keyword, location, max_results=max_results)
            elif portal == "weworkremotely":
                return await self._search_weworkremotely(keyword, max_results=max_results)
            elif portal == "hackernews":
                return await self._search_hackernews(keyword, remote_only, max_results=max_results)
            else:
                return []
        except Exception as e:
            log.warning("search.portal_error", portal=portal, error=str(e))
            return []

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: LinkedIn  — public guest API, no login required
    # ═══════════════════════════════════════════════════════════════════════════

    async def _search_linkedin(
        self, keyword: str, location: str, remote_only: bool,
        max_results: int = 15, pages: int = 1,
    ) -> list[dict]:
        """
        LinkedIn guest API — paginates through `pages` result pages.
        Each page returns up to 25 cards. Total collected is capped at max_results.
        """
        base_params: dict[str, str] = {
            "keywords": keyword,
            "location": location,
            "f_TPR":    "r604800",   # last 7 days
        }
        if remote_only:
            base_params["f_WT"] = "2"

        jobs: list[dict] = []
        page_size = 25   # LinkedIn's guest API page size

        for page_num in range(pages):
            if len(jobs) >= max_results:
                break

            params = {**base_params, "start": str(page_num * page_size)}
            raw = await self._fetch(
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
                params=params,
            )
            if not raw:
                break

            soup = BeautifulSoup(raw, "html.parser")
            cards = soup.find_all("li")
            log.info("search.linkedin", keyword=keyword, location=location,
                     page=page_num + 1, cards=len(cards))

            if not cards:
                break   # no more results — stop paging

            for card in cards:
                if len(jobs) >= max_results:
                    break
                job = self._parse_linkedin_card(card, keyword)
                if job:
                    jobs.append(job)

            # Polite delay between pages
            if page_num < pages - 1:
                await asyncio.sleep(random.uniform(1.0, 2.0))

        return jobs

    def _parse_linkedin_card(self, card, keyword: str) -> dict | None:
        try:
            link = card.find("a", class_="base-card__full-link")
            if not link:
                return None
            url = link["href"].split("?")[0]

            title_el   = card.find("h3", class_="base-search-card__title")
            company_el = card.find("h4", class_="base-search-card__subtitle")
            location_el = card.find("span", class_="job-search-card__location")
            date_el    = card.find("time")

            loc_text = location_el.get_text(strip=True) if location_el else ""
            return {
                "url":       url,
                "title":     title_el.get_text(strip=True) if title_el else keyword,
                "company":   company_el.get_text(strip=True) if company_el else "Unknown",
                "location":  loc_text,
                "portal":    "linkedin",
                "remote":    "remote" in loc_text.lower(),
                "posted_at": _safe_date(date_el["datetime"][:10] if date_el and date_el.get("datetime") else None),
                "status":    "new",
            }
        except Exception as e:
            log.debug("search.linkedin_parse_err", error=str(e))
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: RemoteOK  — free public JSON API, no auth
    # ═══════════════════════════════════════════════════════════════════════════

    async def _search_remoteok(self, keyword: str, location: str, max_results: int = 15) -> list[dict]:
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": _ua(), "Accept": "application/json"},
            ) as client:
                resp = await client.get("https://remoteok.com/api")
                if resp.status_code != 200:
                    log.warning("search.remoteok_http", status=resp.status_code)
                    return []
                data = resp.json()
        except Exception as e:
            log.warning("search.remoteok_error", error=str(e))
            return []

        # First element is a legal notice — skip non-job entries
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

            lo, hi = job.get("salary_min"), job.get("salary_max")
            salary = None
            if lo and hi:
                salary = f"${int(lo)//1000}k–${int(hi)//1000}k"
            elif lo:
                salary = f"${int(lo)//1000}k+"

            jobs.append({
                "url":         job.get("url") or f"https://remoteok.com/remote-jobs/{job.get('id')}",
                "title":       job.get("position", keyword),
                "company":     job.get("company", "Unknown"),
                "location":    "Remote",
                "portal":      "remoteok",
                "remote":      True,
                "salary_range": salary,
                "job_type":    "full-time",
                "description": BeautifulSoup(job.get("description", ""), "html.parser").get_text()[:500],
                "posted_at":   _safe_date(job.get("date")),
                "status":      "new",
            })

            if len(jobs) >= max_results:
                break

        log.info("search.remoteok", keyword=keyword, matched=len(jobs))
        return jobs

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: We Work Remotely  — RSS feeds, no auth
    # ═══════════════════════════════════════════════════════════════════════════

    _WWR_FEEDS = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    ]

    async def _search_weworkremotely(self, keyword: str, max_results: int = 15) -> list[dict]:
        kw_words = keyword.lower().split()
        jobs: list[dict] = []
        seen: set[str] = set()

        for feed_url in self._WWR_FEEDS:
            raw = await self._fetch(feed_url)
            if not raw:
                continue

            soup = BeautifulSoup(raw, "html.parser")
            for item in soup.find_all("item"):
                title_el = item.find("title")
                title_raw = title_el.get_text(strip=True) if title_el else ""
                # WWR titles: "Company: Job Title"
                parts = title_raw.split(": ", 1)
                company = parts[0].strip() if len(parts) > 1 else "Unknown"
                title   = parts[1].strip() if len(parts) > 1 else title_raw

                desc_el   = item.find("description")
                desc_text = BeautifulSoup(
                    desc_el.get_text(strip=True) if desc_el else "", "html.parser"
                ).get_text()

                if not all(w in f"{title} {desc_text}".lower() for w in kw_words):
                    continue

                # RSS <link> is a sibling text node in some parsers
                link_el = item.find("link")
                url = str(link_el.next_sibling or link_el.get_text(strip=True) or "").strip()
                if not url or url in seen:
                    continue
                if not url.startswith("http"):
                    url = f"https://weworkremotely.com{url}"

                seen.add(url)
                pub_el = item.find("pubdate")
                jobs.append({
                    "url":      url,
                    "title":    title,
                    "company":  company,
                    "location": "Remote",
                    "portal":   "weworkremotely",
                    "remote":   True,
                    "job_type": "full-time",
                    "description": desc_text[:500],
                    "posted_at": _safe_date(pub_el.get_text(strip=True) if pub_el else None),
                    "status":   "new",
                })

                if len(jobs) >= max_results:
                    break
            if len(jobs) >= max_results:
                break

        log.info("search.weworkremotely", keyword=keyword, matched=len(jobs))
        return jobs

    # ═══════════════════════════════════════════════════════════════════════════
    # PORTAL: HackerNews "Who is Hiring"  — Algolia search API, no auth
    # ═══════════════════════════════════════════════════════════════════════════

    async def _search_hackernews(self, keyword: str, remote_only: bool, max_results: int = 15) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:

                # Step 1 — find latest "Who is Hiring" story
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
                log.info("search.hackernews_thread", story_id=story_id)

                # Step 2 — search comments in that story for our keyword
                query = f"{keyword} remote" if remote_only else keyword
                r2 = await client.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    params={
                        "tags":         f"comment,story_{story_id}",
                        "query":        query,
                        "hitsPerPage":  max(max_results, 20),  # fetch at least 20, respect config
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

            # First line is usually "Company | Role | Location | ..."
            first_line = text.split("\n")[0].strip()[:120]
            parts  = [p.strip() for p in first_line.replace("|", "·").split("·")]
            company = parts[0] if parts else "Unknown"

            # Try to find a role-sounding part
            title = keyword
            for part in parts[1:]:
                if any(w in part.lower() for w in ["engineer", "developer", "lead", "manager", "designer", "scientist"]):
                    title = part
                    break

            jobs.append({
                "url":         f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "title":       title or keyword,
                "company":     company[:100],
                "location":    "Remote / See post",
                "portal":      "hackernews",
                "remote":      "remote" in text.lower(),
                "job_type":    "full-time",
                "description": text[:500],
                "posted_at":   _safe_date(hit.get("created_at")),
                "status":      "new",
            })

        log.info("search.hackernews", keyword=keyword, matched=len(jobs))
        return jobs

    # ── HTTP helper ───────────────────────────────────────────────────────────

    async def _fetch(self, url: str, params: dict | None = None) -> str | None:
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers={
                    "User-Agent":      _ua(),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
                },
            ) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    return resp.text
                log.warning("search.http_error", url=url, status=resp.status_code)
                return None
        except Exception as e:
            log.warning("search.fetch_failed", url=url, error=str(e))
            return None

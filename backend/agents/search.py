"""
JobForge — Search Agent
Searches job portals for listings matching the user's profile.
Phase 1: LinkedIn (public API). Phase 2: Indeed, Glassdoor, Naukri.
"""

import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from core.config import settings
from agents.base import BaseAgent
from models.job import Job
import structlog

log = structlog.get_logger()


class SearchAgent(BaseAgent):
    name = "search"
    model = settings.llm_model_fast  # fast model, many parallel calls

    SYSTEM_PROMPT = """You are a job search assistant. Given a raw job listing HTML or text,
extract the key details in JSON format.

Return ONLY valid JSON with these fields:
{
  "title": "...",
  "company": "...",
  "location": "...",
  "remote": true/false,
  "salary_range": "...",
  "job_type": "full-time|part-time|contract|internship",
  "description": "... (first 500 chars)",
  "posted_at": "YYYY-MM-DD or null"
}
If a field is not found, use null."""

    async def run(self, query: str, location: str = "remote", portal: str = "linkedin") -> list[dict]:
        """
        Search for jobs matching the query.

        Args:
            query: Job title / keywords (e.g. "Senior Python Developer")
            location: Location string or "remote"
            portal: Which portal to search ("linkedin", "indeed")

        Returns:
            List of raw job dicts ready to be stored in DB.
        """
        await self.emit("started", f"Searching {portal} for '{query}' in {location}...")

        if portal == "linkedin":
            raw_jobs = await self._search_linkedin(query, location)
        else:
            await self.emit("error", f"Portal '{portal}' not yet implemented.")
            return []

        await self.emit("thinking", f"Extracting details from {len(raw_jobs)} listings...")

        jobs = []
        for raw in raw_jobs:
            try:
                parsed = await self._extract_job_details(raw)
                if parsed:
                    jobs.append(parsed)
            except Exception as e:
                log.warning("search.parse_error", error=str(e))

        await self.emit("done", f"Found {len(jobs)} jobs on {portal}.", {"count": len(jobs)})
        return jobs

    async def _search_linkedin(self, query: str, location: str) -> list[dict]:
        """
        Scrape LinkedIn's public job search (no auth required).
        Returns list of raw dicts with url + snippet.
        """
        params = {
            "keywords": query,
            "location": location,
            "f_TPR": "r86400",   # last 24 hours
            "f_WT": "2",          # remote (remove for all)
            "start": "0",
        }
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
        except Exception as e:
            log.warning("search.linkedin_fetch_failed", error=str(e))
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("li")

        raw_jobs = []
        for card in cards[:20]:  # cap at 20 per search
            try:
                link = card.find("a", class_="base-card__full-link")
                job_url = link["href"].split("?")[0] if link else None
                if not job_url:
                    continue

                title_el = card.find("h3", class_="base-search-card__title")
                company_el = card.find("h4", class_="base-search-card__subtitle")
                location_el = card.find("span", class_="job-search-card__location")

                raw_jobs.append({
                    "url": job_url,
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "company": company_el.get_text(strip=True) if company_el else "",
                    "location": location_el.get_text(strip=True) if location_el else "",
                    "portal": "linkedin",
                    "snippet": card.get_text(separator=" ", strip=True)[:800],
                })
            except Exception:
                continue

        return raw_jobs

    async def _extract_job_details(self, raw: dict) -> dict | None:
        """Use LLM to extract structured fields from raw job card text."""
        messages = [
            self.system(self.SYSTEM_PROMPT),
            self.user(f"Job listing snippet:\n{raw.get('snippet', '')[:600]}"),
        ]

        try:
            parsed = await self.chat_json(messages)
        except Exception as e:
            log.warning("search.llm_extract_failed", error=str(e))
            # Fallback: use whatever we already scraped directly
            parsed = {}

        return {
            "title": parsed.get("title") or raw.get("title", "Unknown"),
            "company": parsed.get("company") or raw.get("company", "Unknown"),
            "location": parsed.get("location") or raw.get("location"),
            "url": raw["url"],
            "portal": raw.get("portal", "linkedin"),
            "remote": parsed.get("remote", False),
            "salary_range": parsed.get("salary_range"),
            "job_type": parsed.get("job_type"),
            "description": parsed.get("description"),
            "posted_at": self._parse_date(parsed.get("posted_at")),
        }

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            return None

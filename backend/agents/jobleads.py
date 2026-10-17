"""JobLeads public search connector. No login or LLM calls required."""

import asyncio
import re
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from agents.base import BaseAgent
from core.config import settings


# Country searches select a market without passing the country as a city name.
_COUNTRY_NAMES = {
    "ar": ("argentina",),
    "at": ("austria",),
    "au": ("australia",),
    "be": ("belgium",),
    "br": ("brazil",),
    "ca": ("canada",),
    "ch": ("switzerland",),
    "cl": ("chile",),
    "co": ("colombia",),
    "cr": ("costa rica",),
    "de": ("germany", "deutschland"),
    "dk": ("denmark",),
    "ec": ("ecuador",),
    "es": ("spain",),
    "fi": ("finland",),
    "fr": ("france",),
    "gb": ("united kingdom", "uk", "great britain", "britain"),
    "gr": ("greece",),
    "hk": ("hong kong",),
    "hu": ("hungary",),
    "id": ("indonesia",),
    "ie": ("ireland",),
    "in": ("india",),
    "it": ("italy",),
    "lu": ("luxembourg",),
    "mx": ("mexico",),
    "my": ("malaysia",),
    "nl": ("netherlands", "the netherlands"),
    "no": ("norway",),
    "nz": ("new zealand",),
    "pe": ("peru",),
    "ph": ("philippines", "the philippines"),
    "pl": ("poland",),
    "pt": ("portugal",),
    "qa": ("qatar",),
    "sa": ("saudi arabia",),
    "se": ("sweden",),
    "sg": ("singapore",),
    "tr": ("turkey", "turkiye"),
    "us": ("united states", "united states of america", "usa"),
    "ve": ("venezuela",),
    "za": ("south africa",),
}
_COUNTRY_MARKETS = {
    alias: country
    for country, names in _COUNTRY_NAMES.items()
    for alias in (country, *names)
}


def _resolve_location(location: str) -> tuple[str, str]:
    location = " ".join(location.split())
    country = _COUNTRY_MARKETS.get(location.casefold())
    if country:
        return country, ""
    return settings.jobleads_country, location


class JobLeadsAgent(BaseAgent):
    name = "jobleads"
    model = settings.llm_model_fast

    async def run(
        self, keyword: str, location: str, remote_only: bool = False,
        max_results: int = 15, posted_within_days: int = 7,
    ) -> list[dict]:
        # Reuse the application's HTTP helper without duplicating its policies.
        from agents.search import SearchAgent

        await self.emit("started", f"Searching JobLeads for {keyword} in {location}...")
        country, search_location = _resolve_location(location)
        base = f"https://www.jobleads.com/{country}/jobs"
        is_remote = remote_only or search_location.lower() == "remote"
        if search_location and search_location.lower() not in {"remote", "worldwide", "anywhere"}:
            base += f"/l/{quote(search_location, safe='')}"
        base += f"/q/{quote(keyword.strip(), safe='')}"
        params = {"filter_by_daysReleased": str(posted_within_days)}
        if is_remote:
            params["filter_by_remote"] = "remote"

        jobs: list[dict] = []
        seen: set[str] = set()
        fetcher = SearchAgent()
        for page in range(1, 5):
            raw = await fetcher._fetch(base, params={**params, "page": str(page)})
            if not raw:
                await self.emit("error", "JobLeads search could not be fetched; try again later.")
                return jobs
            soup = BeautifulSoup(raw, "html.parser")
            cards = soup.select('[data-testid="search-job-card"]')
            if not cards:
                await self.emit("thinking", "JobLeads returned no public job cards for this search.")
                break
            new_urls = 0
            for card in cards:
                job = self._parse_card(card)
                if not job or job["url"] in seen:
                    continue
                seen.add(job["url"])
                new_urls += 1
                if is_remote and not job["remote"]:
                    continue
                if job["posted_at"] and job["posted_at"] < datetime.utcnow() - timedelta(days=posted_within_days):
                    continue
                jobs.append(job)
                if len(jobs) >= max_results:
                    break
            if len(jobs) >= max_results or not new_urls or len(cards) < 25:
                break
            await asyncio.sleep(1)

        await self.emit("done", f"Found {len(jobs)} jobs on JobLeads.", {"count": len(jobs)})
        return jobs

    @staticmethod
    def _parse_card(card) -> dict | None:
        def text(test_id: str) -> str:
            element = card.select_one(f'[data-testid="{test_id}"]')
            return element.get_text(" ", strip=True) if element else ""

        link = card.select_one('a[data-testid="search-job-card-link"][href]')
        if not link:
            return None
        parsed = urlsplit(urljoin("https://www.jobleads.com", link["href"]))
        if parsed.hostname != "www.jobleads.com" or "/job/" not in parsed.path:
            return None
        title_el = card.find("h2")
        title = title_el.get_text(" ", strip=True) if title_el else link.get_text(" ", strip=True)
        if not title:
            return None
        company = text("search-job-card-company-name")
        company_line = text("search-job-card-company")
        location = company_line.removeprefix(company).strip(" \u2022")
        posted_at = None
        date_text = text("job-card-date").lower()
        match = re.fullmatch(r"(\d+)\s+(minute|hour|day|week)s? ago", date_text)
        if match:
            posted_at = datetime.utcnow() - timedelta(**{match[2] + "s": int(match[1])})
        elif date_text in {"today", "just now"}:
            posted_at = datetime.utcnow()
        elif date_text == "yesterday":
            posted_at = datetime.utcnow() - timedelta(days=1)
        return {
            "url": parsed._replace(query="", fragment="").geturl(),
            "title": title,
            "company": company or "Unknown",
            "location": location,
            "portal": "jobleads",
            "remote": text("job-card-chip-work-setting").lower() == "remote",
            "salary_range": text("job-card-chip-salary") or None,
            "posted_at": posted_at,
            "status": "new",
        }

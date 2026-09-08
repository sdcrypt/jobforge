"""
JobForge — Research Agent
Gathers company intel before applying: culture, tech stack, recent news.
"""

import httpx
from bs4 import BeautifulSoup
from core.config import settings
from agents.base import BaseAgent
from models.job import Job
import structlog

log = structlog.get_logger()

RESEARCH_PROMPT = """You are a company research assistant helping a job candidate prepare for an application.
Given scraped text about a company, extract useful intel.

Return JSON:
{
  "culture": "2-3 sentence summary of company culture and values",
  "tech_stack": ["Python", "React", ...],
  "recent_news": ["..."],
  "size": "startup|scaleup|enterprise|unknown",
  "red_flags": ["..."],
  "talking_points": ["Mention their focus on X in your cover letter", ...]
}"""


class ResearchAgent(BaseAgent):
    name = "research"
    model = settings.llm_model_smart

    async def run(self, job: Job) -> dict:
        """Research a company before an application is generated."""
        await self.emit("started", f"Researching {job.company}...")

        company_text = await self._scrape_company(job.company, job.url)

        if not company_text:
            await self.emit("done", "Limited public info found — skipping deep research.")
            return {"culture": "Unknown", "tech_stack": [], "talking_points": []}

        await self.emit("thinking", "Analysing company info with LLM...")

        result = await self.chat_json(
            [
                self.system(RESEARCH_PROMPT),
                self.user(f"Company: {job.company}\n\nScraped info:\n{company_text[:2000]}"),
            ]
        )

        await self.emit(
            "done",
            f"Research complete for {job.company}",
            {"tech_stack": result.get("tech_stack", [])},
        )
        return result

    async def _scrape_company(self, company: str, job_url: str) -> str:
        """Try to get company info from their LinkedIn About page or job domain."""
        # Extract domain from job URL as a starting point
        try:
            from urllib.parse import urlparse
            domain = urlparse(job_url).netloc.replace("www.", "")
            about_url = f"https://{domain}/about"
        except Exception:
            return ""

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
        }

        for url in [about_url]:
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        # Remove scripts/styles
                        for tag in soup(["script", "style", "nav", "footer"]):
                            tag.decompose()
                        return soup.get_text(separator=" ", strip=True)[:3000]
            except Exception as e:
                log.debug("research.fetch_failed", url=url, error=str(e))

        return ""

"""
JobForge — Research Agent
Deep-dives into a job posting and scores it against the user's profile.

Steps:
  1. Load job from DB
  2. Try to fetch the full job description from the posting URL
  3. LLM analysis — fit score + sub-scores + strengths / gaps / talking points
  4. Persist everything back to the Job record
"""

import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from sqlalchemy import select

from agents.base import BaseAgent
from core.config import settings
from models.job import Job
import structlog

log = structlog.get_logger()

# HTML tags that carry no useful job-description text
_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript", "form"}


class ResearchAgent(BaseAgent):
    name = "research"
    model = settings.llm_model_smart   # use smarter model for analysis

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self, job_id: str, profile: dict) -> dict:
        """
        Analyse a job posting against the user's profile.
        Updates the Job record in DB and returns the analysis dict.
        """
        await self.emit("started", f"Starting research on job {job_id}…")

        # 1. Load job
        result = await self.db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            await self.emit("error", f"Job {job_id} not found.")
            return {}

        await self.emit("thinking", f"Analysing \"{job.title}\" at {job.company}…")

        # 2. Get description — use stored text or try to scrape the full page
        description = job.description or ""
        if len(description) < 200:
            await self.emit("thinking", "Fetching full job description from posting URL…")
            fetched = await self._fetch_description(job.url)
            if fetched:
                description = fetched
                log.info("research.description_fetched", chars=len(description))

        if not description:
            description = (
                f"{job.title} at {job.company} "
                f"({job.location or 'location not specified'})"
            )

        # 3. LLM analysis
        await self.emit("thinking", "Running AI fit analysis…")
        analysis = await self._analyse(job, description, profile)

        # 4. Persist to DB
        job.fit_score      = analysis.get("fit_score")
        job.tech_score     = analysis.get("tech_score")
        job.exp_score      = analysis.get("exp_score")
        job.location_score = analysis.get("location_score")
        job.growth_score   = analysis.get("growth_score")
        job.strengths      = analysis.get("strengths", [])
        job.gaps           = analysis.get("gaps", [])
        job.fit_summary    = analysis.get("fit_summary", "")
        job.talking_points = analysis.get("talking_points", [])
        job.researched_at  = datetime.utcnow()
        # Cache description if we didn't have it before
        if description and not job.description:
            job.description = description[:4000]

        await self.db.commit()
        await self.db.refresh(job)

        score = job.fit_score or 0
        await self.emit(
            "done",
            f"Research complete — fit score {score:.0f}% for {job.title} @ {job.company}",
            {"job_id": job_id, "fit_score": score},
        )

        return {
            "fit_score":      job.fit_score,
            "tech_score":     job.tech_score,
            "exp_score":      job.exp_score,
            "location_score": job.location_score,
            "growth_score":   job.growth_score,
            "strengths":      job.strengths,
            "gaps":           job.gaps,
            "fit_summary":    job.fit_summary,
            "talking_points": job.talking_points,
            "researched_at":  job.researched_at.isoformat() if job.researched_at else None,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _fetch_description(self, url: str) -> str:
        """
        Try to fetch the full job description from the posting URL.
        Returns plain text (≤5 000 chars), or "" on any failure.
        Works for most portals; LinkedIn / gated portals will return partial text.
        """
        try:
            async with httpx.AsyncClient(
                timeout=12,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return ""

                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup.find_all(_SKIP_TAGS):
                    tag.decompose()

                # Prefer a clearly labelled description section
                main = (
                    soup.find("main")
                    or soup.find(attrs={"id": lambda i: i and "description" in i.lower()})
                    or soup.find(class_=lambda c: c and "description" in c.lower())
                    or soup.find(class_=lambda c: c and "job-detail" in c.lower())
                    or soup.body
                )

                text = (main or soup).get_text(separator=" ", strip=True)
                return " ".join(text.split())[:5000]   # collapse whitespace, cap length
        except Exception as e:
            log.debug("research.fetch_failed", url=url[:80], error=str(e))
            return ""

    async def _analyse(self, job: Job, description: str, profile: dict) -> dict:
        """Ask the LLM to score the job fit and return structured JSON."""

        # Compact profile strings for the prompt
        skills_str = ", ".join(
            f"{s['name']} ({s.get('level', 'intermediate')})"
            for s in (profile.get("skills") or [])[:20]
        ) or "Not specified"

        exp_str = "; ".join(
            f"{e.get('role')} at {e.get('company')} "
            f"({e.get('start', '?')}–{e.get('end', 'present')})"
            for e in (profile.get("experience") or [])[:5]
        ) or "Not specified"

        edu_str = "; ".join(
            f"{e.get('degree')} from {e.get('institution')}"
            for e in (profile.get("education") or [])[:3]
        ) or "Not specified"

        target_roles = ", ".join(profile.get("target_roles") or []) or "Not specified"

        system_msg = (
            "You are an expert career coach and technical recruiter. "
            "Analyse the job posting against the candidate profile and return ONLY valid JSON — "
            "no markdown fences, no explanation, just the JSON object."
        )

        user_msg = f"""CANDIDATE PROFILE
Name: {profile.get('full_name', 'Unknown')}
Headline: {profile.get('headline', 'Not provided')}
Skills: {skills_str}
Experience: {exp_str}
Education: {edu_str}
Remote preference: {profile.get('remote_preference', 'flexible')}
Target roles: {target_roles}
Summary: {(profile.get('summary') or '')[:500]}

JOB POSTING
Title: {job.title}
Company: {job.company}
Location: {job.location or 'Not specified'}{' (Remote)' if job.remote else ''}
Description:
{description[:3000]}

Return exactly this JSON — all fields are required:
{{
  "fit_score": <integer 0-100, overall fit>,
  "tech_score": <integer 0-100, technical skills match>,
  "exp_score": <integer 0-100, seniority / experience level match>,
  "location_score": <integer 0-100, location / remote fit>,
  "growth_score": <integer 0-100, career growth potential>,
  "strengths": ["<specific strength from profile matching the job>", "<strength 2>", "<strength 3>"],
  "gaps": ["<specific gap or missing requirement>", "<gap 2>"],
  "fit_summary": "<2-3 honest sentences: is this a strong fit and why>",
  "talking_points": [
    "<specific thing to highlight in cover letter based on this job>",
    "<another concrete talking point>",
    "<a good question to ask at the interview>"
  ]
}}

Be specific — reference actual skills and experiences from the profile vs the job description."""

        try:
            result = await self.chat_json(
                [self.system(system_msg), self.user(user_msg)]
            )
            # Clamp all score fields to 0–100
            for field in ("fit_score", "tech_score", "exp_score", "location_score", "growth_score"):
                if field in result:
                    result[field] = float(max(0, min(100, result[field])))
            return result
        except Exception as e:
            log.warning("research.llm_failed", error=str(e))
            return {
                "fit_score": 50.0, "tech_score": 50.0, "exp_score": 50.0,
                "location_score": 50.0, "growth_score": 50.0,
                "strengths": [],
                "gaps": ["Analysis failed — check Ollama is running"],
                "fit_summary": "Could not complete AI analysis. Make sure Ollama is running.",
                "talking_points": [],
            }

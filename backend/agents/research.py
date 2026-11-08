"""
JobForge — Research Agent
Deep-dives into a job posting and scores it against the user's profile.

Steps:
  1. Load job from DB
  2. Try to fetch the full job description from the posting URL
  3. LLM analysis — fit score + sub-scores + strengths / gaps / talking points
  4. Persist everything back to the Job record
"""

from datetime import datetime
from sqlalchemy import select

from agents.base import BaseAgent
from core.config import settings
from core.runs import commit_owned
from models.job import Job
import structlog

log = structlog.get_logger()


class ResearchAgent(BaseAgent):
    name = "research"
    model = settings.llm_model_smart   # use smarter model for analysis

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self, job_id: int, profile: dict) -> dict:
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

        from core.job_descriptions import ensure_description
        description = await ensure_description(job, self.emit, fetcher=self._fetch_description)
        await commit_owned(self.db)
        if not description:
            description = f"{job.title} at {job.company}. Description unavailable; state this limitation and do not invent requirements."

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
        await commit_owned(self.db)
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
        from core.job_descriptions import fetch_description
        return await fetch_description(url)

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
{description}

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
            required = {"fit_score", "tech_score", "exp_score", "location_score", "growth_score", "strengths", "gaps", "fit_summary", "talking_points"}
            if required - result.keys():
                raise ValueError("AI analysis omitted required fields.")
            # Clamp all score fields to 0–100
            for field in ("fit_score", "tech_score", "exp_score", "location_score", "growth_score"):
                if field in result:
                    result[field] = float(max(0, min(100, result[field])))
            return result
        except Exception as e:
            log.warning("research.llm_failed", error=str(e))
            raise RuntimeError(f"AI research failed: {e}") from e

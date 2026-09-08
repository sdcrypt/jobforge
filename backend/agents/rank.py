"""
JobForge — Rank Agent
Scores each job against the candidate's profile across 4 dimensions.
Runs jobs in parallel batches for speed.
"""

import asyncio
from core.config import settings
from agents.base import BaseAgent
from models.job import Job
from models.profile import UserProfile
import structlog

log = structlog.get_logger()

SCORE_PROMPT = """You are a career advisor scoring job fit.
Given a candidate profile and job listing, score the fit on 4 dimensions.

Return ONLY valid JSON:
{
  "tech_score": <0-100>,
  "exp_score": <0-100>,
  "location_score": <0-100>,
  "growth_score": <0-100>,
  "overall": <weighted average>,
  "strengths": ["<key strength 1>", "<key strength 2>"],
  "gaps": ["<gap 1>", "<gap 2>"],
  "verdict": "strong_fit|good_fit|weak_fit|no_fit"
}

Scoring rubric:
- tech_score: skills match (languages, frameworks, tools)
- exp_score: years + seniority level alignment
- location_score: location/remote preference match (100 if perfect match)
- growth_score: career trajectory and learning opportunity
- overall: (tech*0.35 + exp*0.25 + location*0.2 + growth*0.2)"""


class RankAgent(BaseAgent):
    name = "rank"
    model = settings.llm_model_smart

    async def run(self, jobs: list[Job], profile: UserProfile) -> list[dict]:
        """
        Score a list of jobs against a candidate profile.
        Returns list of score dicts keyed by job.id.
        """
        await self.emit("started", f"Ranking {len(jobs)} jobs against your profile...")

        profile_summary = self._build_profile_summary(profile)

        # Run in parallel batches of 5
        batch_size = 5
        all_scores = []
        for i in range(0, len(jobs), batch_size):
            batch = jobs[i: i + batch_size]
            await self.emit("thinking", f"Scoring batch {i // batch_size + 1}...")
            scores = await asyncio.gather(
                *[self._score_job(job, profile_summary) for job in batch],
                return_exceptions=True,
            )
            for job, score in zip(batch, scores):
                if isinstance(score, Exception):
                    log.warning("rank.score_failed", job_id=job.id, error=str(score))
                else:
                    all_scores.append({"job_id": job.id, **score})

        all_scores.sort(key=lambda x: x.get("overall", 0), reverse=True)
        await self.emit(
            "done",
            f"Ranked {len(all_scores)} jobs. Top score: {all_scores[0]['overall'] if all_scores else 0:.0f}/100",
            {"ranked_count": len(all_scores)},
        )
        return all_scores

    async def _score_job(self, job: Job, profile_summary: str) -> dict:
        job_summary = (
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location} (Remote: {job.remote})\n"
            f"Type: {job.job_type}\n"
            f"Salary: {job.salary_range or 'not specified'}\n"
            f"Description: {(job.description or '')[:500]}"
        )
        messages = [
            self.system(SCORE_PROMPT),
            self.user(
                f"CANDIDATE PROFILE:\n{profile_summary}\n\n"
                f"JOB LISTING:\n{job_summary}"
            ),
        ]
        return await self.chat_json(messages, temperature=0.1)

    @staticmethod
    def _build_profile_summary(profile: UserProfile) -> str:
        skills = ", ".join(
            [s["name"] for s in (profile.skills or [])]
        )
        exp_lines = []
        for e in (profile.experience or [])[:3]:
            exp_lines.append(f"- {e.get('role')} at {e.get('company')} ({e.get('start')}–{e.get('end')})")

        return (
            f"Name: {profile.full_name}\n"
            f"Target roles: {', '.join(profile.target_roles or [])}\n"
            f"Skills: {skills}\n"
            f"Experience:\n" + "\n".join(exp_lines) + "\n"
            f"Remote preference: {profile.remote_preference or 'any'}\n"
            f"Preferred locations: {', '.join(profile.preferred_locations or [])}\n"
            f"Salary expectation: {profile.salary_min}–{profile.salary_max} {profile.salary_currency or 'USD'}"
        )

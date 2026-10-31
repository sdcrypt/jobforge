import base64

from sqlalchemy import select

from core import database
from core.runs import commit_owned, stage
from models.application import Application
from models.job import Job
from models.profile import UserProfile


async def profile_for_run(db):
    profile = (await db.execute(select(UserProfile).limit(1))).scalar_one_or_none()
    if not profile:
        raise ValueError("Create a profile before running this task.")
    return profile


def profile_context(profile) -> dict:
    return {field: getattr(profile, field) for field in (
        "full_name", "headline", "summary", "skills", "experience", "education", "target_roles", "remote_preference"
    )}


async def rank_pending(db, profile) -> int:
    from agents.rank import RankAgent
    count = 0
    while True:
        pending = (await db.execute(select(Job).where(Job.fit_score == None, Job.status != "dismissed").limit(50))).scalars().all()
        if not pending:
            break
        await stage("rank", f"Ranking next {len(pending)} jobs", count, count + len(pending))
        scores = await RankAgent(db=db).run(jobs=pending, profile=profile)
        for score in scores:
            job = await db.get(Job, score["job_id"])
            if job:
                job.fit_score = float(max(0, min(100, score["overall"])))
                for field in ("tech_score", "exp_score", "location_score", "growth_score", "strengths", "gaps"):
                    setattr(job, field, score.get(field))
                job.status = "ranked"
                count += 1
        await commit_owned(db)
        await stage("rank", f"Ranked {count} jobs", count, count, result={"jobs_ranked": count})
        if len(scores) < len(pending):
            raise RuntimeError(f"Could not rank {len(pending) - len(scores)} jobs; successful scores were saved.")
    await stage("rank", f"Ranking complete: {count} jobs", count, count, done=True, result={"jobs_ranked": count})
    return count


async def research_one(db, job_id):
    from agents.research import ResearchAgent
    job = await db.get(Job, job_id)
    if not job:
        raise ValueError("Job no longer exists.")
    profile = await profile_for_run(db)
    return await ResearchAgent(db=db, job_id=job_id).run(job_id=job_id, profile=profile_context(profile))


async def perform_run(run) -> dict:
    async with database.AsyncSessionLocal() as db:
        if run.kind == "pipeline":
            from agents.pipeline import run_pipeline
            return await run_pipeline(db, config_data=run.payload, config_id=run.config_id)
        if run.kind == "rank":
            return {"jobs_ranked": await rank_pending(db, await profile_for_run(db))}
        if run.kind == "search":
            from agents.search import SearchAgent
            await stage("search", "Searching job portals")
            agent = SearchAgent(db=db)
            raw = await agent.run(**run.payload)
            reports = getattr(agent, "portal_reports", {})
            await stage("search", f"Found {len(raw)} results", len(raw), len(raw), done=True, result={"portal_reports": reports})
            if reports and all(report["status"] == "failed" for report in reports.values()):
                raise RuntimeError("All configured portals failed. See portal reports for details.")
            from agents.pipeline import store_jobs
            await stage("store", "Saving new jobs")
            count = await store_jobs(db, raw)
            await commit_owned(db)
            await stage("store", f"Saved {count} new jobs", count, count, done=True)
            return {"new_jobs_found": count, "portal_reports": reports}
        if run.kind == "research":
            await stage("research", "Analysing job fit")
            result = await research_one(db, run.job_id)
            await stage("research", "Job research completed", 1, 1, done=True)
            return result
        if run.kind == "docgen":
            from api.routes.applications import _run_docgen
            application = (await db.execute(select(Application).where(Application.job_id == run.job_id))).scalar_one_or_none()
            if not application:
                raise ValueError("Application no longer exists.")
            application.document_status = "generating"
            application.document_error = None
            await commit_owned(db)
            await stage("documents", "Generating resume and cover letter")
            await _run_docgen(run.job_id)
            await stage("documents", "Application documents are ready", 2, 2, done=True)
            return {"job_id": run.job_id}
        if run.kind == "apply":
            from api.routes.applications import _run_apply
            await stage("apply", "Opening application for review")
            result = await _run_apply(run.job_id)
            await stage("apply", "Application assistance finished", done=True)
            return result
        if run.kind == "resume_parse":
            from core.resume_parser import ResumeParser
            await stage("resume", "Extracting and parsing resume")
            parser = ResumeParser(db=db)
            content = base64.b64decode(run.payload["content"])
            parsed = await (parser.parse_pdf(content) if run.payload["extension"] == ".pdf" else parser.parse_docx(content))
            await stage("resume", "Resume parsed; review before saving", 1, 1, done=True)
            return {"parsed": parsed}
        raise ValueError(f"Unknown task kind: {run.kind}")

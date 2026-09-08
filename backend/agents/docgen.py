"""
JobForge — DocGen Agent
Generates a tailored one-pager resume + cover letter for a specific job.
Output: HTML (rendered to PDF via WeasyPrint). No LaTeX required.
"""

import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from core.config import settings
from agents.base import BaseAgent
from models.job import Job
from models.profile import UserProfile
import structlog

log = structlog.get_logger()

ONE_PAGER_PROMPT = """You are an expert technical resume writer.
Given a candidate profile and a job listing, create a tailored one-pager resume.

Rules:
- Highlight skills and experience most relevant to THIS specific job
- Use strong action verbs and quantified achievements where possible
- Keep to ONE page worth of content
- Match the tone to the job (startup = conversational, enterprise = formal)
- Do NOT invent experience — only use what's in the profile

Return JSON with this structure:
{
  "headline": "Senior Python Engineer | FastAPI · PostgreSQL · AWS",
  "summary": "3-sentence tailored summary for this role",
  "highlighted_skills": ["Python", "FastAPI", ...],
  "experience": [
    {
      "company": "...", "role": "...", "period": "...",
      "bullets": ["Achieved X by doing Y, resulting in Z", ...]
    }
  ],
  "education": [{"institution": "...", "degree": "...", "year": ...}],
  "why_this_role": "One sentence on why this candidate fits perfectly"
}"""

COVER_LETTER_PROMPT = """You are an expert cover letter writer.
Write a compelling, specific cover letter for this job application.

Rules:
- Opening: Hook + role name + company name
- Body: 2 paragraphs max — specific achievements relevant to the JD
- Closing: Clear call to action
- Tone: Match the company culture (read between the lines of the JD)
- Length: 250–350 words max
- Do NOT be generic — reference SPECIFIC things from the job description

Return plain text only (no JSON, no markdown)."""


class DocGenAgent(BaseAgent):
    name = "docgen"
    model = settings.llm_model_smart

    def __init__(self, db=None, job_id: str | None = None):
        super().__init__(db=db, job_id=job_id)
        # Set up Jinja2 for HTML template rendering
        template_dir = Path(__file__).parent.parent / "templates"
        self.jinja = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )

    async def run(self, job: Job, profile: UserProfile) -> dict:
        """
        Generate one-pager + cover letter for a specific job.

        Returns:
            {
                "one_pager_html": "...",
                "one_pager_path": "/documents/...",
                "cover_letter_text": "...",
                "cover_letter_path": "/documents/..."
            }
        """
        await self.emit("started", f"Generating docs for {job.title} at {job.company}...")

        job_summary = self._job_summary(job)
        profile_summary = self._profile_summary(profile)

        # ── Step 1: Generate tailored one-pager content ──────────────────
        await self.emit("thinking", "Tailoring your one-pager to the job...")
        one_pager_data = await self.chat_json(
            [
                self.system(ONE_PAGER_PROMPT),
                self.user(
                    f"CANDIDATE PROFILE:\n{profile_summary}\n\n"
                    f"JOB LISTING:\n{job_summary}"
                ),
            ]
        )

        # ── Step 2: Generate cover letter ────────────────────────────────
        await self.emit("thinking", "Writing your cover letter...")
        cover_letter = await self.chat(
            [
                self.system(COVER_LETTER_PROMPT),
                self.user(
                    f"CANDIDATE:\n{profile.full_name}\n{profile_summary}\n\n"
                    f"JOB:\n{job_summary}"
                ),
            ],
            temperature=0.6,
        )

        # ── Step 3: Render HTML one-pager ────────────────────────────────
        await self.emit("thinking", "Rendering PDF documents...")
        html = self._render_one_pager(one_pager_data, profile)
        one_pager_path = await self._save_pdf(html, job, "one_pager")
        cover_path = await self._save_cover_letter(cover_letter, job)

        await self.emit(
            "done",
            f"Documents ready for {job.title} at {job.company}",
            {"one_pager_path": one_pager_path, "cover_letter_path": cover_path},
        )

        return {
            "one_pager_html": html,
            "one_pager_path": one_pager_path,
            "cover_letter_text": cover_letter,
            "cover_letter_path": cover_path,
        }

    def _render_one_pager(self, data: dict, profile: UserProfile) -> str:
        """Render Jinja2 HTML template with generated content."""
        try:
            template = self.jinja.get_template("one_pager.html")
            return template.render(
                profile=profile,
                data=data,
            )
        except Exception as e:
            log.warning("docgen.template_render_failed", error=str(e))
            # Minimal fallback HTML
            return self._fallback_html(data, profile)

    def _fallback_html(self, data: dict, profile: UserProfile) -> str:
        """Simple inline HTML when template file isn't available yet."""
        bullets_html = ""
        for exp in data.get("experience", []):
            bullets = "".join(f"<li>{b}</li>" for b in exp.get("bullets", []))
            bullets_html += f"""
            <div class="role">
              <strong>{exp.get('role')}</strong> · {exp.get('company')} · {exp.get('period')}
              <ul>{bullets}</ul>
            </div>"""

        skills = ", ".join(data.get("highlighted_skills", []))
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: Inter, sans-serif; max-width: 800px; margin: 40px auto; color: #1a1a1a; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .headline {{ color: #4b5563; margin-bottom: 16px; }}
  .section {{ margin-top: 20px; border-top: 1px solid #e5e7eb; padding-top: 12px; }}
  .section h2 {{ font-size: 1rem; text-transform: uppercase; letter-spacing: 1px; color: #6b7280; }}
  .role {{ margin-bottom: 12px; }}
  ul {{ margin: 4px 0 0 16px; }}
  li {{ margin-bottom: 4px; font-size: 0.9rem; }}
  .skills {{ color: #1d4ed8; }}
</style></head>
<body>
  <h1>{profile.full_name}</h1>
  <div class="headline">{data.get('headline', '')}</div>
  <div>{profile.email} · {profile.phone or ''} · {profile.location or ''}</div>

  <div class="section">
    <h2>Summary</h2>
    <p>{data.get('summary', '')}</p>
  </div>

  <div class="section">
    <h2>Skills</h2>
    <p class="skills">{skills}</p>
  </div>

  <div class="section">
    <h2>Experience</h2>
    {bullets_html}
  </div>
</body></html>"""

    async def _save_pdf(self, html: str, job: Job, doc_type: str) -> str:
        """Convert HTML to PDF and save to documents directory."""
        docs_dir = Path(settings.documents_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)

        slug = f"{job.company}_{job.title}".lower().replace(" ", "_")[:40]
        html_path = docs_dir / f"{doc_type}_{slug}.html"
        pdf_path = docs_dir / f"{doc_type}_{slug}.pdf"

        html_path.write_text(html, encoding="utf-8")

        try:
            from weasyprint import HTML
            HTML(string=html).write_pdf(str(pdf_path))
            return str(pdf_path)
        except ImportError:
            log.warning("docgen.weasyprint_not_installed — saving HTML only")
            return str(html_path)

    async def _save_cover_letter(self, text: str, job: Job) -> str:
        docs_dir = Path(settings.documents_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)
        slug = f"{job.company}_{job.title}".lower().replace(" ", "_")[:40]
        path = docs_dir / f"cover_letter_{slug}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)

    @staticmethod
    def _job_summary(job: Job) -> str:
        return (
            f"Title: {job.title}\nCompany: {job.company}\n"
            f"Location: {job.location} (Remote: {job.remote})\n"
            f"Description:\n{(job.description or '')[:1000]}"
        )

    @staticmethod
    def _profile_summary(profile: UserProfile) -> str:
        skills = ", ".join([s["name"] for s in (profile.skills or [])])
        return (
            f"Name: {profile.full_name}\nEmail: {profile.email}\n"
            f"Skills: {skills}\nHeadline: {profile.headline or ''}\n"
            f"Summary: {profile.summary or ''}"
        )

"""
JobForge — DocGen Agent
Generates a tailored one-pager resume + cover letter for a specific job.

Flow:
  1. LLM generates tailored content JSON  (one-pager sections)
  2. LLM generates cover letter text      (plain paragraphs)
  3. Jinja2 renders HTML templates        (one_pager.html / cover_letter.html)
  4. WeasyPrint converts HTML → PDF       (saved to /documents)

Output:
  - one_pager.html   (browser preview)
  - one_pager.pdf    (download)
  - cover_letter.html
  - cover_letter.pdf
"""

import re
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from core.config import settings
from agents.base import BaseAgent
from models.job import Job
from models.profile import UserProfile
import structlog

log = structlog.get_logger()

# ── Prompts ────────────────────────────────────────────────────────────────

ONE_PAGER_PROMPT = """You are an expert technical resume writer who specialises in
tailoring resumes for specific job postings.

Given the candidate profile and job listing below, produce ONE-PAGER resume content.

RULES:
- Highlight skills and experience most relevant to THIS specific job
- Use strong action verbs + quantified achievements (numbers, percentages, scale)
- Reorder experience bullets to lead with what matters most for this role
- Keep it to what fits on ONE A4 page
- Match company tone: startup = concise & direct, enterprise = formal
- NEVER invent experience — only use what the profile contains

Return ONLY valid JSON (no markdown, no explanation):
{
  "headline": "Role Title | Tech1 · Tech2 · Tech3",
  "summary": "2-3 sentence tailored pitch for this exact role",
  "highlighted_skills": ["Skill1", "Skill2", ...],
  "experience": [
    {
      "role": "Job Title",
      "company": "Company Name",
      "period": "Jan 2022 – Present",
      "bullets": [
        "Led X, resulting in Y% improvement in Z",
        "Built A using B, serving C users"
      ]
    }
  ],
  "education": [
    {"degree": "B.Sc. Computer Science", "institution": "University Name", "year": 2020}
  ],
  "why_this_role": "One sentence on why this candidate is a strong fit"
}"""

COVER_LETTER_PROMPT = """You are an expert cover letter writer.
Write a compelling, specific cover letter for this job application.

RULES:
- Opening paragraph: hook + role name + company name (show you know them)
- Middle paragraph(s): 2 specific achievements directly relevant to this JD
- Closing paragraph: clear call to action, enthusiasm, next steps
- Tone: match the company culture (read the JD carefully)
- Length: 3-4 paragraphs, 260-320 words total
- Be SPECIFIC — reference actual things from the job description
- Do NOT be generic or use clichés like "I am excited to apply"

Return the cover letter as plain paragraphs separated by a blank line.
Do NOT include the salutation or closing — those are added by the template.
Return ONLY the body paragraphs, nothing else."""


class DocGenAgent(BaseAgent):
    name = "docgen"
    model = settings.llm_model_smart

    def __init__(self, db=None, job_id: str | None = None):
        super().__init__(db=db, job_id=job_id)
        template_dir = Path(__file__).parent.parent / "templates"
        self.jinja = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html"]),
        )

    async def run(self, job: Job, profile: UserProfile) -> dict:
        """
        Generate one-pager + cover letter for a specific job.

        Returns:
            {
                "one_pager_html":     str,
                "one_pager_path":     str,   # .html path (or .pdf if WeasyPrint available)
                "cover_letter_html":  str,
                "cover_letter_path":  str,
                "cover_letter_text":  str,   # plain text paragraphs
            }
        """
        await self.emit(
            "started",
            f"Generating documents for {job.title} at {job.company}...",
        )

        profile_ctx = self._build_profile_context(profile)
        job_ctx = self._build_job_context(job)

        # ── Step 1: Generate one-pager content ─────────────────────────────
        await self.emit("thinking", "Tailoring your resume to the job description...")
        one_pager_data = await self._generate_one_pager_data(job_ctx, profile_ctx)

        # ── Step 2: Generate cover letter ──────────────────────────────────
        await self.emit("thinking", "Writing your cover letter...")
        cover_paragraphs = await self._generate_cover_letter(job_ctx, profile_ctx)

        # ── Step 3: Render HTML ─────────────────────────────────────────────
        await self.emit("thinking", "Rendering documents...")
        one_pager_html = self._render_one_pager(one_pager_data, profile)
        cover_letter_html = self._render_cover_letter(cover_paragraphs, profile, job)
        cover_letter_text = "\n\n".join(cover_paragraphs)

        # ── Step 4: Save files ──────────────────────────────────────────────
        slug = self._slug(job.company, job.title)
        docs_dir = Path(settings.documents_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)

        one_pager_path = await self._save(
            one_pager_html, docs_dir / f"one_pager_{slug}"
        )
        cover_letter_path = await self._save(
            cover_letter_html, docs_dir / f"cover_letter_{slug}"
        )

        await self.emit(
            "done",
            f"Documents ready for {job.title} at {job.company} ✓",
            {
                "one_pager_path": one_pager_path,
                "cover_letter_path": cover_letter_path,
            },
        )

        return {
            "one_pager_html": one_pager_html,
            "one_pager_path": one_pager_path,
            "cover_letter_html": cover_letter_html,
            "cover_letter_path": cover_letter_path,
            "cover_letter_text": cover_letter_text,
        }

    # ── LLM generation ────────────────────────────────────────────────────

    async def _generate_one_pager_data(self, job_ctx: str, profile_ctx: str) -> dict:
        messages = [
            self.system(ONE_PAGER_PROMPT),
            self.user(
                f"CANDIDATE PROFILE:\n{profile_ctx}\n\n"
                f"JOB LISTING:\n{job_ctx}"
            ),
        ]
        data = await self.chat_json(messages, temperature=0.3)

        # Validate minimum fields
        data.setdefault("headline", "")
        data.setdefault("summary", "")
        data.setdefault("highlighted_skills", [])
        data.setdefault("experience", [])
        data.setdefault("education", [])
        data.setdefault("why_this_role", "")
        return data

    async def _generate_cover_letter(self, job_ctx: str, profile_ctx: str) -> list[str]:
        messages = [
            self.system(COVER_LETTER_PROMPT),
            self.user(
                f"CANDIDATE:\n{profile_ctx}\n\n"
                f"JOB:\n{job_ctx}"
            ),
        ]
        text = await self.chat(messages, temperature=0.55, max_tokens=600)

        # Split into paragraphs, clean up
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        # Remove any accidental salutation/closing lines the LLM added
        paragraphs = [
            p for p in paragraphs
            if not p.lower().startswith(("dear ", "sincerely", "best regards", "yours"))
        ]
        return paragraphs or [text.strip()]

    # ── HTML rendering ────────────────────────────────────────────────────

    def _render_one_pager(self, data: dict, profile: UserProfile) -> str:
        try:
            tmpl = self.jinja.get_template("one_pager.html")
            return tmpl.render(profile=profile, data=data)
        except Exception as e:
            log.warning("docgen.template_error", error=str(e))
            return self._fallback_one_pager(data, profile)

    def _render_cover_letter(
        self, paragraphs: list[str], profile: UserProfile, job: Job
    ) -> str:
        try:
            tmpl = self.jinja.get_template("cover_letter.html")
            return tmpl.render(
                profile=profile,
                job=job,
                paragraphs=paragraphs,
                date=datetime.utcnow().strftime("%B %d, %Y"),
            )
        except Exception as e:
            log.warning("docgen.cover_letter_template_error", error=str(e))
            return self._fallback_cover_letter(paragraphs, profile, job)

    # ── File saving ───────────────────────────────────────────────────────

    async def _save(self, html: str, base_path: Path) -> str:
        """Save HTML and attempt PDF conversion. Returns the saved file path."""
        html_path = base_path.with_suffix(".html")
        html_path.write_text(html, encoding="utf-8")

        try:
            from weasyprint import HTML
            pdf_path = base_path.with_suffix(".pdf")
            HTML(string=html).write_pdf(str(pdf_path))
            log.info("docgen.pdf_saved", path=str(pdf_path))
            return str(pdf_path)
        except ImportError:
            log.warning("docgen.weasyprint_missing — HTML saved only")
        except Exception as e:
            log.warning("docgen.pdf_failed", error=str(e))

        return str(html_path)

    # ── Context builders ──────────────────────────────────────────────────

    @staticmethod
    def _build_profile_context(profile: UserProfile) -> str:
        skills = ", ".join(s["name"] for s in (profile.skills or []))
        exp_lines = []
        for e in (profile.experience or [])[:4]:
            bullets = "; ".join(e.get("highlights", [])[:3])
            exp_lines.append(
                f"- {e.get('role')} at {e.get('company')} "
                f"({e.get('start')}–{e.get('end')}): {bullets}"
            )
        edu_lines = [
            f"- {e.get('degree')} · {e.get('institution')} ({e.get('year')})"
            for e in (profile.education or [])
        ]
        return (
            f"Name: {profile.full_name}\n"
            f"Email: {profile.email}\n"
            f"Location: {profile.location or 'Not specified'}\n"
            f"Headline: {profile.headline or ''}\n"
            f"Summary: {profile.summary or ''}\n"
            f"Skills: {skills}\n"
            f"Experience:\n" + "\n".join(exp_lines) + "\n"
            f"Education:\n" + "\n".join(edu_lines)
        )

    @staticmethod
    def _build_job_context(job: Job) -> str:
        return (
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location or 'Not specified'} "
            f"(Remote: {job.remote})\n"
            f"Type: {job.job_type or 'Not specified'}\n"
            f"Salary: {job.salary_range or 'Not specified'}\n"
            f"Description:\n{(job.description or '')[:1500]}"
        )

    # ── Fallback HTML (if templates missing) ─────────────────────────────

    @staticmethod
    def _fallback_one_pager(data: dict, profile: UserProfile) -> str:
        skills_html = "".join(
            f'<span style="background:#eff6ff;border:1px solid #bfdbfe;'
            f'border-radius:3px;padding:2px 6px;margin:2px;font-size:8pt">'
            f'{s}</span>'
            for s in data.get("highlighted_skills", [])
        )
        exp_html = ""
        for e in data.get("experience", []):
            bullets = "".join(f"<li>{b}</li>" for b in e.get("bullets", []))
            exp_html += (
                f"<div style='margin-bottom:8px'>"
                f"<strong>{e.get('role')}</strong> · {e.get('company')} "
                f"<span style='color:#94a3b8;font-size:8pt'>{e.get('period')}</span>"
                f"<ul style='margin:3px 0 0 14px'>{bullets}</ul></div>"
            )
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:sans-serif;max-width:750px;margin:30px auto;color:#1a1a2e;font-size:10pt}}
h1{{font-size:20pt;margin-bottom:2px}}h2{{font-size:8pt;text-transform:uppercase;
letter-spacing:1px;color:#2563eb;border-bottom:1px solid #e2e8f0;margin:10px 0 5px}}</style>
</head><body>
<h1>{profile.full_name}</h1>
<p style="color:#2563eb">{data.get('headline','')}</p>
<p style="color:#64748b;font-size:8pt">{profile.email} · {profile.phone or ''} · {profile.location or ''}</p>
<h2>Summary</h2><p>{data.get('summary','')}</p>
<h2>Skills</h2><div>{skills_html}</div>
<h2>Experience</h2>{exp_html}
</body></html>"""

    @staticmethod
    def _fallback_cover_letter(
        paragraphs: list[str], profile: UserProfile, job: Job
    ) -> str:
        body = "".join(f"<p style='margin-bottom:12px'>{p}</p>" for p in paragraphs)
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:serif;max-width:700px;margin:40px auto;font-size:11pt;line-height:1.6}}</style>
</head><body>
<p><strong>{profile.full_name}</strong><br>{profile.email}</p>
<p style="margin-top:20px">{datetime.utcnow().strftime('%B %d, %Y')}</p>
<p style="margin-top:20px"><strong>{job.company}</strong><br>Hiring Team</p>
<p style="margin-top:20px">Dear Hiring Team,</p>
{body}
<p>Sincerely,<br><strong>{profile.full_name}</strong></p>
</body></html>"""

    @staticmethod
    def _slug(company: str, title: str) -> str:
        raw = f"{company}_{title}".lower()
        return re.sub(r"[^a-z0-9_]", "_", raw)[:45]

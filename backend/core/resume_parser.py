"""
JobForge — Resume Parser
Extracts text from PDF / DOCX and uses the LLM to convert it
into structured profile JSON ready to auto-fill the UI form.
"""

import io
from agents.base import BaseAgent
from core.config import settings

# ── LLM Prompt ────────────────────────────────────────────────────────────────

PARSE_PROMPT = """\
You are an expert resume parser. Extract every piece of information from the
resume text and return it as structured JSON.

Return ONLY valid JSON matching this exact schema (no markdown, no explanation):
{
  "full_name": "string",
  "email": "string",
  "phone": "string or null",
  "location": "City, Country — or null",
  "linkedin_url": "full URL or null",
  "github_url": "full URL or null",
  "portfolio_url": "full URL or null",
  "headline": "one-line title, e.g. 'Senior Software Engineer · Python · 8 yrs'",
  "summary": "2-3 sentence professional summary (write one if not present)",
  "skills": [
    {"name": "Python", "level": "expert"},
    {"name": "React", "level": "intermediate"}
  ],
  "experience": [
    {
      "company": "Company Name",
      "role": "Job Title",
      "start": "Jan 2022",
      "end": "Present",
      "highlights": [
        "Led X resulting in Y% improvement",
        "Built A using B, serving C users"
      ]
    }
  ],
  "education": [
    {"institution": "University Name", "degree": "B.Tech Computer Science", "year": 2019}
  ],
  "target_roles": ["Senior Software Engineer", "Tech Lead"],
  "remote_preference": "hybrid",
  "salary_min": null,
  "salary_max": null
}

Rules:
- skill level must be exactly "beginner", "intermediate", or "expert"
  (infer from years of use, seniority, and context)
- Extract ALL work experience — do not truncate
- For current roles, use "Present" as the end date
- target_roles: infer 2-3 roles based on their trajectory (not what's on the resume)
- remote_preference must be one of: "remote", "hybrid", "onsite"
- If any field cannot be found, use null — never make up data
- highlights: keep each bullet factual and under 15 words; trim fluff
"""


class ResumeParser(BaseAgent):
    """Parses an uploaded resume file into structured profile data."""

    name = "resume_parser"
    model = settings.llm_model_smart

    # ── Public entry points ───────────────────────────────────────────────

    async def parse_pdf(self, file_bytes: bytes) -> dict:
        text = self._extract_pdf(file_bytes)
        return await self._parse_text(text)

    async def parse_docx(self, file_bytes: bytes) -> dict:
        text = self._extract_docx(file_bytes)
        return await self._parse_text(text)

    # ── Text extraction ───────────────────────────────────────────────────

    @staticmethod
    def _extract_pdf(file_bytes: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError(
                "pypdf is not installed. It should be in requirements.txt — "
                "rebuild the Docker image."
            )
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
        text = "\n".join(pages).strip()
        if not text:
            raise ValueError(
                "Could not extract text from this PDF. "
                "It may be a scanned image. Try a Word (.docx) version instead."
            )
        return text

    @staticmethod
    def _extract_docx(file_bytes: bytes) -> str:
        try:
            from docx import Document
        except ImportError:
            raise RuntimeError(
                "python-docx is not installed. It should be in requirements.txt — "
                "rebuild the Docker image."
            )
        doc = Document(io.BytesIO(file_bytes))
        lines = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also grab text from tables (some resumes use tables for layout)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        lines.append(cell.text.strip())
        text = "\n".join(lines).strip()
        if not text:
            raise ValueError("Could not extract text from the DOCX file.")
        return text

    # ── LLM parsing ───────────────────────────────────────────────────────

    async def _parse_text(self, raw_text: str) -> dict:
        await self.emit("started", "Reading your resume…")

        # Trim to avoid token overflow — 4000 chars ≈ ~1000 tokens, plenty for a resume
        text = raw_text[:5000]

        await self.emit("thinking", "Extracting profile information…")
        messages = [
            self.system(PARSE_PROMPT),
            self.user(f"RESUME:\n\n{text}"),
        ]
        data = await self.chat_json(messages, temperature=0.1)

        # Ensure required lists are lists, not None
        for key in ("skills", "experience", "education", "target_roles"):
            if not isinstance(data.get(key), list):
                data[key] = []

        # Ensure skill levels are valid
        valid_levels = {"beginner", "intermediate", "expert"}
        for sk in data.get("skills", []):
            if sk.get("level") not in valid_levels:
                sk["level"] = "intermediate"

        await self.emit("done", "Resume parsed — review and save your profile ✓")
        return data

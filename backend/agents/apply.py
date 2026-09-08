"""
JobForge — Apply Agent
Uses Playwright to auto-fill and submit job application forms.
Always requires user confirmation before final submit.
"""

from core.config import settings
from agents.base import BaseAgent
from models.job import Job
from models.profile import UserProfile
from models.application import Application
import structlog

log = structlog.get_logger()

FORM_ANALYSIS_PROMPT = """You are a form-filling assistant.
Given the HTML of a job application form, identify all input fields and map them
to candidate profile fields.

Return JSON:
{
  "fields": [
    {
      "selector": "CSS selector or name attribute",
      "label": "human readable label",
      "type": "text|email|phone|textarea|select|file",
      "profile_field": "full_name|email|phone|location|linkedin_url|resume_file|cover_letter|custom",
      "value_hint": "what value to fill if profile_field is 'custom'"
    }
  ],
  "submit_selector": "CSS selector of the submit button",
  "requires_account": true/false,
  "notes": "any special instructions"
}"""


class ApplyAgent(BaseAgent):
    name = "apply"
    model = settings.llm_model_smart

    async def run(
        self,
        job: Job,
        profile: UserProfile,
        application: Application,
        auto_submit: bool = False,  # Always False — human confirms
    ) -> dict:
        """
        Attempt to auto-fill a job application form.

        Steps:
        1. Open the job application URL with Playwright
        2. Scrape the form HTML
        3. LLM maps fields to profile data
        4. Fill all fields
        5. Pause and show user a screenshot for review
        6. User confirms → submit (or user edits manually)

        Returns:
            {"status": "filled"|"submitted"|"requires_manual", "screenshot_path": "..."}
        """
        await self.emit("started", f"Opening application form for {job.title} at {job.company}...")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            await self.emit(
                "error",
                "Playwright not installed. Run: pip install playwright && playwright install chromium",
            )
            return {"status": "error", "message": "Playwright not installed"}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)  # visible so user can watch
            page = await browser.new_page()

            # Step 1: Navigate to application URL
            apply_url = job.url
            await self.emit("thinking", f"Navigating to {apply_url}")
            try:
                await page.goto(apply_url, timeout=15000)
            except Exception as e:
                await self.emit("error", f"Could not open URL: {e}")
                await browser.close()
                return {"status": "requires_manual", "message": str(e)}

            # Step 2: Get page HTML for form analysis
            html = await page.content()

            # Step 3: LLM analyses the form
            await self.emit("thinking", "Analysing application form fields...")
            form_data = await self._analyse_form(html)

            if form_data.get("requires_account"):
                await self.emit(
                    "done",
                    "This job requires an account login. Please apply manually.",
                )
                await browser.close()
                return {"status": "requires_manual", "message": "Login required"}

            # Step 4: Fill fields
            await self.emit("thinking", "Filling in your details...")
            filled_count = 0
            for field in form_data.get("fields", []):
                value = self._get_field_value(field, profile, application)
                if value and field.get("selector"):
                    try:
                        el = page.locator(field["selector"]).first
                        if field["type"] == "file" and application.one_pager_path:
                            await el.set_input_files(application.one_pager_path)
                        elif field["type"] in ("text", "email", "phone", "textarea"):
                            await el.fill(str(value))
                        filled_count += 1
                    except Exception as e:
                        log.debug("apply.fill_failed", field=field.get("label"), error=str(e))

            # Step 5: Screenshot for user review
            screenshot_path = f"./documents/apply_preview_{job.id[:8]}.png"
            await page.screenshot(path=screenshot_path, full_page=True)

            await self.emit(
                "done",
                f"Filled {filled_count} fields. Waiting for your review before submitting.",
                {
                    "screenshot_path": screenshot_path,
                    "filled_count": filled_count,
                    "submit_selector": form_data.get("submit_selector"),
                    "notes": form_data.get("notes", ""),
                },
            )

            # Keep browser open for manual review / final submit
            # Frontend will call /api/applications/{id}/confirm-submit to proceed
            return {
                "status": "filled",
                "screenshot_path": screenshot_path,
                "filled_count": filled_count,
                "browser_open": True,
                "notes": form_data.get("notes", ""),
            }

    async def _analyse_form(self, html: str) -> dict:
        """Use LLM to map form fields to profile data."""
        # Trim HTML to keep token count manageable
        trimmed = html[:4000]
        try:
            return await self.chat_json(
                [
                    self.system(FORM_ANALYSIS_PROMPT),
                    self.user(f"Form HTML:\n{trimmed}"),
                ]
            )
        except Exception as e:
            log.warning("apply.form_analysis_failed", error=str(e))
            return {"fields": [], "requires_account": False}

    @staticmethod
    def _get_field_value(field: dict, profile: UserProfile, application: Application) -> str | None:
        """Map a form field to the correct profile value."""
        mapping = {
            "full_name": profile.full_name,
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location,
            "linkedin_url": profile.linkedin_url,
            "resume_file": application.one_pager_path,
            "cover_letter": application.cover_letter_text,
        }
        pf = field.get("profile_field", "custom")
        if pf in mapping:
            return mapping[pf]
        return field.get("value_hint")

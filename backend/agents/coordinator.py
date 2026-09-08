"""
JobForge — Coordinator Agent
Orchestrates all other agents. Decides what to do next based on
the current state of the job pipeline.
"""

from core.config import settings
from agents.base import BaseAgent
import structlog

log = structlog.get_logger()


class CoordinatorAgent(BaseAgent):
    name = "coordinator"
    model = settings.llm_model_smart  # needs the smarter model

    SYSTEM_PROMPT = """You are JobForge's coordinator AI.
Your job is to orchestrate a job search pipeline by deciding which agents to
run and in what order, based on the current pipeline state.

Available agents:
- search    : Scrapes job portals for new listings
- rank      : Scores and ranks jobs against the candidate's profile
- docgen    : Generates a tailored one-pager and cover letter
- research  : Researches a company before applying
- apply     : Submits a job application via browser automation

Always respond in JSON with this shape:
{
  "next_actions": [
    {"agent": "<name>", "reason": "<why>", "priority": "high|medium|low"}
  ],
  "summary": "<one sentence on the current pipeline state>"
}"""

    async def run(self, pipeline_state: dict) -> dict:
        """
        Given the current pipeline state, decide next actions.

        pipeline_state example:
        {
            "new_jobs": 12,
            "unranked_jobs": 8,
            "ready_to_apply": 3,
            "pending_docs": 2,
        }
        """
        await self.emit("started", "Analysing pipeline state...")

        messages = [
            self.system(self.SYSTEM_PROMPT),
            self.user(
                f"Current pipeline state:\n{pipeline_state}\n\n"
                "What should we do next?"
            ),
        ]

        result = await self.chat_json(messages)

        await self.emit(
            "done",
            result.get("summary", "Pipeline analysed."),
            {"next_actions": result.get("next_actions", [])},
        )

        return result

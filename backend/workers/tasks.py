"""
JobForge — Celery Tasks
"""

import asyncio
import sys
from pathlib import Path

APP_DIR = str(Path(__file__).resolve().parents[1])

from workers.celery_app import celery_app

_runner = None


def ensure_app_path():
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)


def run_async(coroutine):
    global _runner
    if _runner is None:
        _runner = asyncio.Runner()
    return _runner.run(coroutine)


@celery_app.task(name="workers.tasks.execute_run", acks_late=True, reject_on_worker_lost=True)
def execute_run(run_id: int):
    ensure_app_path()
    from core.runs import execute_run as execute
    return run_async(execute(run_id))


@celery_app.task(name="workers.tasks.maintain_runs")
def maintain_runs():
    ensure_app_path()
    from workers.scheduler import tick
    return run_async(tick())

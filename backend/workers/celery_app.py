"""
JobForge — Celery app
Runs background + scheduled tasks (job search pipeline).

Start worker:
  celery -A workers.celery_app worker --loglevel=info

Start scheduler (for periodic tasks):
  celery -A workers.celery_app beat --loglevel=info
"""

from celery import Celery
from celery.schedules import crontab
from core.config import settings

celery_app = Celery(
    "jobforge",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Scheduled tasks
    beat_schedule={
        "search-pipeline-every-12h": {
            "task": "workers.tasks.run_search_pipeline",
            "schedule": crontab(minute=0, hour="*/12"),  # every 12 hours
        },
    },
)

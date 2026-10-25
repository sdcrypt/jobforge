"""
JobForge — Celery app
Runs background + scheduled tasks (job search pipeline).

Start worker:
  celery -A workers.celery_app worker --loglevel=info

Start scheduler (for periodic tasks):
  celery -A workers.celery_app beat --loglevel=info
"""

from celery import Celery
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
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    task_soft_time_limit=3300,
    task_time_limit=3600,
    task_publish_retry=False,
    beat_schedule_filename="/tmp/jobforge-celerybeat-schedule",
    # Scheduled tasks
    beat_schedule={
        "maintain-runs-every-minute": {
            "task": "workers.tasks.maintain_runs",
            "schedule": 60.0,
        },
    },
)

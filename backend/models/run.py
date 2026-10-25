import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    active_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    retry_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trigger: Mapped[str] = mapped_column(String(30), default="manual")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    stage: Mapped[str] = mapped_column(String(60), default="queued")
    stages: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    execution_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

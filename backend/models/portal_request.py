"""Remember request spacing and portal cooldowns across worker restarts."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class PortalRequestState(Base):
    __tablename__ = "portal_request_states"

    host: Mapped[str] = mapped_column(String(255), primary_key=True)
    next_request_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

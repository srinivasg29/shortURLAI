from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ShortUrl(Base):
    __tablename__ = "short_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    click_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

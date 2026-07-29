from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ShortUrl
from app.shortcode import generate_code

_MAX_CODE_ATTEMPTS = 5

# Path segments already served by the app; never hand these out as a
# generated short code even though a collision is astronomically unlikely.
RESERVED_CODES = {"health", "metrics", "docs", "redoc", "openapi.json", "api", "favicon.ico"}


class CodeGenerationExhausted(Exception):
    pass


class InvalidTargetUrl(Exception):
    pass


def _raise_if_self_referential(target_url: str, base_redirect_url: str) -> None:
    target_host = urlparse(target_url).hostname
    base_host = urlparse(base_redirect_url).hostname
    if target_host and base_host and target_host.lower() == base_host.lower():
        raise InvalidTargetUrl("target_url must not point back at this shortener (redirect loop)")


def create_short_url(
    db: Session, target_url: str, expires_in_days: int | None = None
) -> ShortUrl:
    settings = get_settings()
    _raise_if_self_referential(target_url, settings.base_redirect_url)

    for _ in range(_MAX_CODE_ATTEMPTS):
        code = generate_code(settings.default_alias_length)
        if code not in RESERVED_CODES and db.query(ShortUrl).filter(ShortUrl.code == code).first() is None:
            break
    else:
        raise CodeGenerationExhausted(
            f"could not generate a unique code after {_MAX_CODE_ATTEMPTS} attempts"
        )

    days = expires_in_days if expires_in_days is not None else settings.default_expiry_days
    expires_at = datetime.now(UTC) + timedelta(days=days) if days is not None else None

    short_url = ShortUrl(code=code, target_url=target_url, expires_at=expires_at)
    db.add(short_url)
    db.commit()
    db.refresh(short_url)
    return short_url


def get_by_code(db: Session, code: str) -> ShortUrl | None:
    return db.query(ShortUrl).filter(ShortUrl.code == code).first()


def is_expired(short_url: ShortUrl) -> bool:
    expires_at = short_url.expires_at
    if expires_at is None:
        return False
    # SQLite round-trips DateTime(timezone=True) values as naive; treat a
    # naive value as UTC rather than let the aware/naive comparison raise.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < datetime.now(UTC)


def record_click(db: Session, short_url: ShortUrl) -> None:
    short_url.click_count += 1
    short_url.last_clicked_at = datetime.now(UTC)
    db.add(short_url)
    db.commit()

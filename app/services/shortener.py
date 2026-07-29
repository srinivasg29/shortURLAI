from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ShortUrl
from app.shortcode import generate_code

_MAX_CODE_ATTEMPTS = 5


class CodeGenerationExhausted(Exception):
    pass


def create_short_url(db: Session, target_url: str) -> ShortUrl:
    settings = get_settings()

    for _ in range(_MAX_CODE_ATTEMPTS):
        code = generate_code(settings.default_alias_length)
        if db.query(ShortUrl).filter(ShortUrl.code == code).first() is None:
            break
    else:
        raise CodeGenerationExhausted(
            f"could not generate a unique code after {_MAX_CODE_ATTEMPTS} attempts"
        )

    expires_at = None
    if settings.default_expiry_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=settings.default_expiry_days)

    short_url = ShortUrl(code=code, target_url=target_url, expires_at=expires_at)
    db.add(short_url)
    db.commit()
    db.refresh(short_url)
    return short_url


def get_by_code(db: Session, code: str) -> ShortUrl | None:
    return db.query(ShortUrl).filter(ShortUrl.code == code).first()


def record_click(db: Session, short_url: ShortUrl) -> None:
    short_url.click_count += 1
    short_url.last_clicked_at = datetime.now(UTC)
    db.add(short_url)
    db.commit()

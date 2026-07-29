from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
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


class AliasAlreadyTaken(Exception):
    pass


def _raise_if_self_referential(target_url: str, base_redirect_url: str) -> None:
    target_host = urlparse(target_url).hostname
    base_host = urlparse(base_redirect_url).hostname
    if target_host and base_host and target_host.lower() == base_host.lower():
        raise InvalidTargetUrl("target_url must not point back at this shortener (redirect loop)")


def _resolve_custom_alias(db: Session, custom_alias: str) -> str:
    # Format/length are already enforced by ShortenRequest's Field
    # constraints (schemas.py) before this is ever called; this only
    # covers what the request schema can't know about - the reserved-word
    # list and whether the code is already in use.
    if custom_alias in RESERVED_CODES:
        raise AliasAlreadyTaken(f"{custom_alias!r} is a reserved path and cannot be used")
    if db.query(ShortUrl).filter(ShortUrl.code == custom_alias).first() is not None:
        raise AliasAlreadyTaken(f"{custom_alias!r} is already in use")
    return custom_alias


def _generate_random_code(db: Session, alias_length: int) -> str:
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = generate_code(alias_length)
        if code not in RESERVED_CODES and db.query(ShortUrl).filter(ShortUrl.code == code).first() is None:
            return code
    raise CodeGenerationExhausted(
        f"could not generate a unique code after {_MAX_CODE_ATTEMPTS} attempts"
    )


def create_short_url(
    db: Session,
    target_url: str,
    expires_in_days: int | None = None,
    custom_alias: str | None = None,
) -> ShortUrl:
    settings = get_settings()
    _raise_if_self_referential(target_url, settings.base_redirect_url)

    code = (
        _resolve_custom_alias(db, custom_alias)
        if custom_alias is not None
        else _generate_random_code(db, settings.default_alias_length)
    )

    days = expires_in_days if expires_in_days is not None else settings.default_expiry_days
    expires_at = datetime.now(UTC) + timedelta(days=days) if days is not None else None

    short_url = ShortUrl(code=code, target_url=target_url, expires_at=expires_at)
    db.add(short_url)
    try:
        db.commit()
    except IntegrityError as exc:
        # The pre-commit uniqueness check above is optimistic (check-then-
        # insert): a concurrent request can still win the race between the
        # check and this commit. The DB's own unique constraint on `code`
        # is the real guarantee - catch its violation and surface it the
        # same way as a caught-in-time collision, rather than a raw 500.
        db.rollback()
        if custom_alias is not None:
            raise AliasAlreadyTaken(f"{custom_alias!r} is already in use") from exc
        raise CodeGenerationExhausted(
            f"generated code {code!r} collided with a concurrent request"
        ) from exc
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

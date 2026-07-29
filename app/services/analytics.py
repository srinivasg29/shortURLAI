from sqlalchemy.orm import Session

from app.models import ShortUrl
from app.services.shortener import get_by_code


def get_stats(db: Session, code: str) -> ShortUrl | None:
    return get_by_code(db, code)

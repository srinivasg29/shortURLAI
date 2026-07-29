from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.cache import get_cache
from app.database import SessionLocal, get_db
from app.services.shortener import get_by_code, record_click

router = APIRouter(tags=["redirect"])


def _record_click_by_code(code: str) -> None:
    db = SessionLocal()
    try:
        short_url = get_by_code(db, code)
        if short_url is not None:
            record_click(db, short_url)
    finally:
        db.close()


@router.get("/{code}")
def redirect_to_target(
    code: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> RedirectResponse:
    cache = get_cache()

    target_url = cache.get(code)
    if target_url is None:
        short_url = get_by_code(db, code)
        if short_url is None:
            raise HTTPException(status_code=404, detail="short code not found")
        target_url = short_url.target_url
        cache.set(code, target_url)

    background_tasks.add_task(_record_click_by_code, code)
    return RedirectResponse(url=target_url, status_code=302)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import StatsResponse
from app.services.analytics import get_stats

router = APIRouter(tags=["analytics"])


@router.get("/api/urls/{code}/stats", response_model=StatsResponse)
def url_stats(code: str, db: Session = Depends(get_db)) -> StatsResponse:
    short_url = get_stats(db, code)
    if short_url is None:
        raise HTTPException(status_code=404, detail="short code not found")

    return StatsResponse(
        code=short_url.code,
        target_url=short_url.target_url,
        created_at=short_url.created_at,
        expires_at=short_url.expires_at,
        click_count=short_url.click_count,
        last_clicked_at=short_url.last_clicked_at,
    )

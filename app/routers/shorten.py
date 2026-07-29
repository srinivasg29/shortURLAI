from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import ShortenRequest, ShortenResponse
from app.services.shortener import CodeGenerationExhausted, InvalidTargetUrl, create_short_url

router = APIRouter(tags=["shorten"])


@router.post("/api/shorten", response_model=ShortenResponse, status_code=201)
def shorten_url(payload: ShortenRequest, db: Session = Depends(get_db)) -> ShortenResponse:
    settings = get_settings()

    try:
        short_url = create_short_url(
            db, str(payload.target_url), expires_in_days=payload.expires_in_days
        )
    except InvalidTargetUrl as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CodeGenerationExhausted as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ShortenResponse(
        code=short_url.code,
        short_url=f"{settings.base_redirect_url.rstrip('/')}/{short_url.code}",
        target_url=short_url.target_url,
        created_at=short_url.created_at,
        expires_at=short_url.expires_at,
    )

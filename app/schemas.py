from datetime import datetime

from pydantic import BaseModel, HttpUrl


class ShortenRequest(BaseModel):
    target_url: HttpUrl


class ShortenResponse(BaseModel):
    code: str
    short_url: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None


class StatsResponse(BaseModel):
    code: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None
    click_count: int
    last_clicked_at: datetime | None

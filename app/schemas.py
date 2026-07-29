from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

MAX_TARGET_URL_LENGTH = 2048


class ShortenRequest(BaseModel):
    target_url: HttpUrl = Field(max_length=MAX_TARGET_URL_LENGTH)
    expires_in_days: int | None = Field(default=None, gt=0)


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

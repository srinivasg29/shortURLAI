from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

MAX_TARGET_URL_LENGTH = 2048

# Alphanumeric plus hyphen/underscore, matching what generate_code() itself
# could produce - a custom_alias should be at least as constrained as an
# auto-generated code, both for URL-safety and to avoid ambiguity about
# what counts as a "valid" code once aliases are involved.
CUSTOM_ALIAS_PATTERN = r"^[A-Za-z0-9_-]+$"
MIN_CUSTOM_ALIAS_LENGTH = 3
MAX_CUSTOM_ALIAS_LENGTH = 32


class ShortenRequest(BaseModel):
    target_url: HttpUrl = Field(max_length=MAX_TARGET_URL_LENGTH)
    expires_in_days: int | None = Field(default=None, gt=0)
    custom_alias: str | None = Field(
        default=None,
        min_length=MIN_CUSTOM_ALIAS_LENGTH,
        max_length=MAX_CUSTOM_ALIAS_LENGTH,
        pattern=CUSTOM_ALIAS_PATTERN,
    )


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

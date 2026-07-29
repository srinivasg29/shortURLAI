import pytest

from app.services.shortener import (
    CodeGenerationExhausted,
    InvalidTargetUrl,
    create_short_url,
    get_by_code,
    is_expired,
    record_click,
)


def test_create_short_url_generates_code(db_session):
    short_url = create_short_url(db_session, "https://example.com/a")
    assert short_url.code
    assert short_url.target_url == "https://example.com/a"
    assert short_url.click_count == 0
    assert short_url.expires_at is None


def test_create_short_url_rejects_self_referential_target(db_session):
    with pytest.raises(InvalidTargetUrl):
        create_short_url(db_session, "http://localhost:8000/loop")


def test_create_short_url_with_expiry(db_session):
    short_url = create_short_url(db_session, "https://example.com/b", expires_in_days=1)
    assert short_url.expires_at is not None
    assert not is_expired(short_url)


def test_get_by_code_roundtrip(db_session):
    created = create_short_url(db_session, "https://example.com/c")
    fetched = get_by_code(db_session, created.code)
    assert fetched is not None
    assert fetched.id == created.id


def test_get_by_code_missing_returns_none(db_session):
    assert get_by_code(db_session, "doesnotexist") is None


def test_record_click_increments_counter(db_session):
    short_url = create_short_url(db_session, "https://example.com/d")
    record_click(db_session, short_url)
    record_click(db_session, short_url)
    assert short_url.click_count == 2
    assert short_url.last_clicked_at is not None


def test_create_short_url_exhausts_after_max_attempts(db_session, monkeypatch):
    import app.services.shortener as shortener_module

    monkeypatch.setattr(shortener_module, "generate_code", lambda length: "AAAAAAA")
    create_short_url(db_session, "https://example.com/first")

    with pytest.raises(CodeGenerationExhausted):
        create_short_url(db_session, "https://example.com/second")


def test_create_short_url_skips_reserved_codes(db_session, monkeypatch):
    import app.services.shortener as shortener_module

    codes = iter(["health", "goodcode"])
    monkeypatch.setattr(shortener_module, "generate_code", lambda length: next(codes))

    short_url = create_short_url(db_session, "https://example.com/reserved-test")
    assert short_url.code == "goodcode"

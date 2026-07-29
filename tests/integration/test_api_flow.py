def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_shorten_redirect_stats_flow(client):
    resp = client.post("/api/shorten", json={"target_url": "https://example.com/flow"})
    assert resp.status_code == 201
    body = resp.json()
    code = body["code"]
    assert body["target_url"] == "https://example.com/flow"

    redirect_resp = client.get(f"/{code}", follow_redirects=False)
    assert redirect_resp.status_code == 302
    assert redirect_resp.headers["location"] == "https://example.com/flow"

    stats_resp = client.get(f"/api/urls/{code}/stats")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["click_count"] == 1


def test_redirect_missing_code_404(client):
    resp = client.get("/doesnotexist123")
    assert resp.status_code == 404


def test_stats_missing_code_404(client):
    resp = client.get("/api/urls/doesnotexist123/stats")
    assert resp.status_code == 404


def test_shorten_rejects_invalid_url(client):
    resp = client.post("/api/shorten", json={"target_url": "not-a-url"})
    assert resp.status_code == 422


def test_shorten_rejects_self_referential_url(client):
    resp = client.post("/api/shorten", json={"target_url": "http://localhost:8000/x"})
    assert resp.status_code == 422


def test_shorten_rejects_non_positive_expiry(client):
    resp = client.post(
        "/api/shorten", json={"target_url": "https://example.com/e", "expires_in_days": 0}
    )
    assert resp.status_code == 422


def test_expired_redirect_returns_410(client, monkeypatch):
    import app.routers.redirect as redirect_module

    resp = client.post(
        "/api/shorten",
        json={"target_url": "https://example.com/expiring", "expires_in_days": 1},
    )
    code = resp.json()["code"]

    monkeypatch.setattr(redirect_module, "is_expired", lambda short_url: True)

    redirect_resp = client.get(f"/{code}", follow_redirects=False)
    assert redirect_resp.status_code == 410


def test_shorten_returns_503_when_codes_exhausted(client, monkeypatch):
    import app.routers.shorten as shorten_module
    from app.services.shortener import CodeGenerationExhausted

    def _always_exhausted(db, target_url, expires_in_days=None):
        raise CodeGenerationExhausted("no codes left")

    monkeypatch.setattr(shorten_module, "create_short_url", _always_exhausted)

    resp = client.post("/api/shorten", json={"target_url": "https://example.com/exhausted"})
    assert resp.status_code == 503

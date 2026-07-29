from orchestrator.codebase_map import identify_impacted_modules


def test_identifies_click_counter_module():
    matches = identify_impacted_modules("Refactor the analytics click-counter for thread-safety")
    assert "app/services/shortener.py" in matches


def test_identifies_redirect_module():
    matches = identify_impacted_modules("Add allowlisting to the redirect handler")
    assert "app/routers/redirect.py" in matches


def test_identifies_shorten_module():
    matches = identify_impacted_modules("Add rate limiting to the shorten endpoint")
    assert "app/routers/shorten.py" in matches


def test_no_match_returns_empty_list():
    matches = identify_impacted_modules("Completely unrelated gibberish xyz")
    assert matches == []


def test_deduplicates_matches():
    matches = identify_impacted_modules("shorten endpoint that creates a short code")
    assert matches.count("app/routers/shorten.py") == 1

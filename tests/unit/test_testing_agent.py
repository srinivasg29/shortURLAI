from orchestrator.agents import testing


def test_run_no_applied_diff_is_proposal_only(monkeypatch):
    monkeypatch.setattr(testing, "is_live", lambda: False)

    result = testing.run({"normalized_spec": "spec", "code_diffs": []})

    [tr] = result["test_results"]
    assert tr["executed"] is False
    assert tr["passed"] is True
    assert "no applied code change" in tr["detail"]
    assert result["llm_mode"] == "mock"


def test_run_mock_mode_with_applied_diff_is_still_proposal_only(monkeypatch):
    monkeypatch.setattr(testing, "is_live", lambda: False)

    state = {
        "normalized_spec": "spec",
        "code_diffs": [{"path": "app/x.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = testing.run(state)

    [tr] = result["test_results"]
    assert tr["executed"] is False
    assert "unavailable or failed" in tr["detail"]


def test_run_live_mode_generates_and_executes_a_passing_test(monkeypatch, tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()
    (target_dir / "greeter.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    monkeypatch.setattr(testing, "is_live", lambda: True)
    monkeypatch.setattr(testing, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        testing,
        "call_llm",
        lambda *a, **k: "def test_greet():\n    assert 1 + 1 == 2\n",
    )

    state = {
        "normalized_spec": "spec",
        "code_diffs": [{"path": "app/greeter.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = testing.run(state)

    [tr] = result["test_results"]
    assert tr["executed"] is True
    assert tr["passed"] is True
    assert "llm_mode" not in result

    generated = tmp_path / "tests" / "unit" / "test_greeter_generated.py"
    assert generated.exists()


def test_run_live_mode_generates_and_executes_a_failing_test(monkeypatch, tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()
    (target_dir / "greeter.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    monkeypatch.setattr(testing, "is_live", lambda: True)
    monkeypatch.setattr(testing, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        testing,
        "call_llm",
        lambda *a, **k: "def test_broken():\n    assert 1 == 2\n",
    )

    state = {
        "normalized_spec": "spec",
        "code_diffs": [{"path": "app/greeter.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = testing.run(state)

    [tr] = result["test_results"]
    assert tr["executed"] is True
    assert tr["passed"] is False


def test_run_live_mode_falls_back_on_invalid_syntax(monkeypatch, tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()
    (target_dir / "greeter.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    monkeypatch.setattr(testing, "is_live", lambda: True)
    monkeypatch.setattr(testing, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(testing, "call_llm", lambda *a, **k: "def broken(:\n")

    state = {
        "normalized_spec": "spec",
        "code_diffs": [{"path": "app/greeter.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = testing.run(state)

    [tr] = result["test_results"]
    assert tr["executed"] is False
    assert result["llm_mode"] == "mock"


def test_run_live_mode_falls_back_when_llm_raises(monkeypatch, tmp_path):
    target_dir = tmp_path / "app"
    target_dir.mkdir()
    (target_dir / "greeter.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    monkeypatch.setattr(testing, "is_live", lambda: True)
    monkeypatch.setattr(testing, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        testing, "call_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    state = {
        "normalized_spec": "spec",
        "code_diffs": [{"path": "app/greeter.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = testing.run(state)

    [tr] = result["test_results"]
    assert tr["executed"] is False


def test_run_live_mode_falls_back_when_target_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(testing, "is_live", lambda: True)
    monkeypatch.setattr(testing, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(testing, "call_llm", lambda *a, **k: "should not be called")

    state = {
        "normalized_spec": "spec",
        "code_diffs": [{"path": "app/missing.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = testing.run(state)

    [tr] = result["test_results"]
    assert tr["executed"] is False


def test_strip_markdown_fence_removes_fence():
    assert testing._strip_markdown_fence("```python\nx = 1\n```") == "x = 1"
    assert testing._strip_markdown_fence("x = 1") == "x = 1"


def test_run_targets_the_last_applied_diff_not_an_earlier_one(monkeypatch, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "first.py").write_text("x = 1\n", encoding="utf-8")
    (app_dir / "second.py").write_text("y = 2\n", encoding="utf-8")

    monkeypatch.setattr(testing, "is_live", lambda: True)
    monkeypatch.setattr(testing, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(testing, "call_llm", lambda *a, **k: "def test_ok():\n    assert True\n")

    state = {
        "normalized_spec": "spec",
        "code_diffs": [
            {"path": "app/first.py", "diff": "", "summary": "", "applied": True},
            {"path": "app/second.py", "diff": "", "summary": "", "applied": True},
        ],
    }
    result = testing.run(state)

    [tr] = result["test_results"]
    # Both diffs are applied=True; the most recent one (last in the list,
    # i.e. the most recent Coding Agent run) must win.
    assert tr["name"] == "tests/unit/test_second_generated.py"

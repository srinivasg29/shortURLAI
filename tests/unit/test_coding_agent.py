from orchestrator.agents import coding


def _base_state(normalized_spec: str) -> dict:
    return {
        "normalized_spec": normalized_spec,
        "architecture_decisions": [
            {
                "decision": "d",
                "rationale": "r",
                "approved_by": "system:auto_approve",
                "timestamp": "t",
            }
        ],
    }


def test_run_mock_mode_produces_unapplied_proposal(monkeypatch):
    monkeypatch.setattr(coding, "is_live", lambda: False)

    result = coding.run(_base_state("Refactor the analytics click-counter"))

    [diff] = result["code_diffs"]
    assert diff["applied"] is False
    assert diff["path"] == "app/services/shortener.py"
    assert diff["diff"] == ""

    [entry] = result["gate_log"]
    assert entry["gate_id"] == "gate_3"
    assert entry["passed"] is True
    assert result["llm_mode"] == "mock"


def test_run_mock_mode_with_no_identifiable_target(monkeypatch):
    monkeypatch.setattr(coding, "is_live", lambda: False)

    result = coding.run(_base_state("Completely unrelated gibberish xyz"))

    [diff] = result["code_diffs"]
    assert diff["path"] == "UNSPECIFIED"
    assert diff["applied"] is False


def test_run_live_mode_applies_edit_and_writes_file(monkeypatch, tmp_path):
    target_dir = tmp_path / "app" / "services"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "shortener.py"
    target_file.write_text("def before():\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(coding, "is_live", lambda: True)
    monkeypatch.setattr(coding, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coding, "call_llm", lambda *a, **k: "def after():\n    pass\n")
    monkeypatch.setattr(coding, "_run_static_checks", lambda path: (True, "ruff check passed"))

    result = coding.run(_base_state("Refactor the analytics click-counter"))

    assert target_file.read_text(encoding="utf-8") == "def after():\n    pass\n"

    [diff] = result["code_diffs"]
    assert diff["applied"] is True
    assert diff["path"] == "app/services/shortener.py"
    assert "-def before" in diff["diff"]
    assert "+def after" in diff["diff"]
    # A successful live apply must not touch llm_mode at all (see planning
    # agent's equivalent test) - only a degrade-to-mock path sets it.
    assert "llm_mode" not in result

    [entry] = result["gate_log"]
    assert entry["passed"] is True


def test_run_live_mode_falls_back_on_invalid_syntax(monkeypatch, tmp_path):
    target_dir = tmp_path / "app" / "services"
    target_dir.mkdir(parents=True)
    (target_dir / "shortener.py").write_text("def before():\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(coding, "is_live", lambda: True)
    monkeypatch.setattr(coding, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coding, "call_llm", lambda *a, **k: "def broken(:\n")

    result = coding.run(_base_state("Refactor the analytics click-counter"))

    [diff] = result["code_diffs"]
    assert diff["applied"] is False
    assert result["llm_mode"] == "mock"
    # File on disk must be untouched.
    assert (
        tmp_path / "app" / "services" / "shortener.py"
    ).read_text(encoding="utf-8") == "def before():\n    pass\n"


def test_run_live_mode_falls_back_when_llm_raises(monkeypatch, tmp_path):
    target_dir = tmp_path / "app" / "services"
    target_dir.mkdir(parents=True)
    (target_dir / "shortener.py").write_text("def before():\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(coding, "is_live", lambda: True)
    monkeypatch.setattr(coding, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        coding, "call_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    result = coding.run(_base_state("Refactor the analytics click-counter"))

    [diff] = result["code_diffs"]
    assert diff["applied"] is False
    assert result["llm_mode"] == "mock"


def test_run_live_mode_falls_back_when_target_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(coding, "is_live", lambda: True)
    monkeypatch.setattr(coding, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coding, "call_llm", lambda *a, **k: "should not be called")

    result = coding.run(_base_state("Refactor the analytics click-counter"))

    [diff] = result["code_diffs"]
    assert diff["applied"] is False


def test_run_live_mode_falls_back_when_no_target_identified(monkeypatch):
    monkeypatch.setattr(coding, "is_live", lambda: True)

    def _fail_if_called(*a, **k):
        raise AssertionError("call_llm should not be called without a target file")

    monkeypatch.setattr(coding, "call_llm", _fail_if_called)

    result = coding.run(_base_state("Completely unrelated gibberish xyz"))

    [diff] = result["code_diffs"]
    assert diff["applied"] is False
    assert diff["path"] == "UNSPECIFIED"


def test_run_live_mode_no_op_when_llm_returns_identical_content(monkeypatch, tmp_path):
    target_dir = tmp_path / "app" / "services"
    target_dir.mkdir(parents=True)
    content = "def before():\n    pass\n"
    (target_dir / "shortener.py").write_text(content, encoding="utf-8")

    monkeypatch.setattr(coding, "is_live", lambda: True)
    monkeypatch.setattr(coding, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coding, "call_llm", lambda *a, **k: content)

    result = coding.run(_base_state("Refactor the analytics click-counter"))

    [diff] = result["code_diffs"]
    assert diff["applied"] is False


def test_static_check_failure_fails_gate_3(monkeypatch, tmp_path):
    target_dir = tmp_path / "app" / "services"
    target_dir.mkdir(parents=True)
    (target_dir / "shortener.py").write_text("def before():\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(coding, "is_live", lambda: True)
    monkeypatch.setattr(coding, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(coding, "call_llm", lambda *a, **k: "def after():\n    pass\n")
    monkeypatch.setattr(coding, "_run_static_checks", lambda path: (False, "E501 line too long"))

    result = coding.run(_base_state("Refactor the analytics click-counter"))

    [entry] = result["gate_log"]
    assert entry["passed"] is False
    assert entry["detail"] == "E501 line too long"


def test_run_static_checks_real_ruff_pass_and_fail(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")
    passed, detail = coding._run_static_checks(str(good))
    assert passed is True

    bad = tmp_path / "bad.py"
    bad.write_text("import os\n", encoding="utf-8")  # unused import
    passed, detail = coding._run_static_checks(str(bad))
    assert passed is False
    assert detail


def test_strip_markdown_fence_removes_fence():
    assert coding._strip_markdown_fence("```python\nx = 1\n```") == "x = 1"
    assert coding._strip_markdown_fence("x = 1") == "x = 1"

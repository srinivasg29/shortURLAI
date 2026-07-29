from orchestrator.agents import documentation


def test_run_no_applied_diff_is_proposal_only(monkeypatch, tmp_path):
    monkeypatch.setattr(documentation, "is_live", lambda: False)
    monkeypatch.setattr(documentation, "_repo_root", lambda: tmp_path)

    result = documentation.run({"normalized_spec": "spec", "code_diffs": [], "run_id": "r1"})

    [dd] = result["doc_diffs"]
    assert dd["applied"] is False
    assert dd["diff"] == ""
    assert not (tmp_path / "docs" / "CHANGELOG.md").exists()


def test_run_mock_mode_appends_template_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(documentation, "is_live", lambda: False)
    monkeypatch.setattr(documentation, "_repo_root", lambda: tmp_path)

    state = {
        "normalized_spec": "Add vanity aliases",
        "run_id": "abcdef12-0000-0000-0000-000000000000",
        "code_diffs": [
            {"path": "app/x.py", "diff": "d", "summary": "s", "applied": True},
        ],
    }
    result = documentation.run(state)

    [dd] = result["doc_diffs"]
    assert dd["applied"] is True
    assert "app/x.py" in dd["diff"]
    assert result["llm_mode"] == "mock"

    changelog = (tmp_path / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Add vanity aliases" in changelog
    assert "abcdef12" in changelog


def test_run_appends_to_existing_changelog_rather_than_overwriting(monkeypatch, tmp_path):
    monkeypatch.setattr(documentation, "is_live", lambda: False)
    monkeypatch.setattr(documentation, "_repo_root", lambda: tmp_path)

    changelog_path = tmp_path / "docs" / "CHANGELOG.md"
    changelog_path.parent.mkdir(parents=True)
    changelog_path.write_text("# Changelog\n\n- existing entry\n", encoding="utf-8")

    state = {
        "normalized_spec": "a new change",
        "run_id": "r1",
        "code_diffs": [{"path": "app/x.py", "diff": "d", "summary": "s", "applied": True}],
    }
    documentation.run(state)

    content = changelog_path.read_text(encoding="utf-8")
    assert "existing entry" in content
    assert "a new change" in content


def test_run_live_mode_uses_llm_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(documentation, "is_live", lambda: True)
    monkeypatch.setattr(documentation, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(documentation, "call_llm", lambda *a, **k: "A real generated entry.")

    state = {
        "normalized_spec": "spec",
        "run_id": "r1",
        "code_diffs": [{"path": "app/x.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = documentation.run(state)

    assert "llm_mode" not in result
    changelog = (tmp_path / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "A real generated entry." in changelog


def test_run_live_mode_falls_back_to_template_when_llm_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(documentation, "is_live", lambda: True)
    monkeypatch.setattr(documentation, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        documentation, "call_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    state = {
        "normalized_spec": "spec",
        "run_id": "r1",
        "code_diffs": [{"path": "app/x.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = documentation.run(state)

    assert result["llm_mode"] == "mock"
    changelog = (tmp_path / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Updated app/x.py" in changelog


def test_run_live_mode_falls_back_when_llm_returns_blank(monkeypatch, tmp_path):
    monkeypatch.setattr(documentation, "is_live", lambda: True)
    monkeypatch.setattr(documentation, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(documentation, "call_llm", lambda *a, **k: "   ")

    state = {
        "normalized_spec": "spec",
        "run_id": "r1",
        "code_diffs": [{"path": "app/x.py", "diff": "d", "summary": "s", "applied": True}],
    }
    result = documentation.run(state)

    assert result["llm_mode"] == "mock"

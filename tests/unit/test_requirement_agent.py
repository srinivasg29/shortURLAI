from orchestrator.agents import requirement


def test_well_defined_requirement_has_no_ambiguity(monkeypatch):
    monkeypatch.setattr(requirement, "is_live", lambda: False)

    state = {"raw_requirement": "Add a POST /api/shorten endpoint that accepts a target URL."}
    result = requirement.run(state)

    assert result["identified_ambiguities"] == []
    assert result["normalized_spec"] == state["raw_requirement"]
    assert result["llm_mode"] == "mock"


def test_ambiguous_security_requirement_flags_interpretations(monkeypatch):
    monkeypatch.setattr(requirement, "is_live", lambda: False)

    state = {"raw_requirement": "make the service more secure"}
    result = requirement.run(state)

    assert len(result["identified_ambiguities"]) >= 2
    assert "underspecified" in result["normalized_spec"].lower()


def test_gate_log_entry_is_well_formed(monkeypatch):
    monkeypatch.setattr(requirement, "is_live", lambda: False)

    result = requirement.run({"raw_requirement": "Refactor the click counter."})
    [entry] = result["gate_log"]

    assert entry["gate_id"] == "gate_0"
    assert entry["node"] == "requirement_agent"
    assert entry["passed"] is True
    assert entry["exit_criteria"] == "intake normalized, ambiguity flagged"


def test_falls_back_to_heuristic_when_llm_call_fails(monkeypatch):
    monkeypatch.setattr(requirement, "is_live", lambda: True)
    monkeypatch.setattr(
        requirement, "call_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    result = requirement.run({"raw_requirement": "Add analytics for click counts."})

    assert result["llm_mode"] == "mock"
    assert result["normalized_spec"] == "Add analytics for click counts."


def test_uses_live_llm_response_when_available(monkeypatch):
    monkeypatch.setattr(requirement, "is_live", lambda: True)
    monkeypatch.setattr(
        requirement,
        "call_llm",
        lambda *a, **k: (
            '{"requirement_summary": "s", "identified_ambiguities": [], '
            '"normalized_spec": "normalized"}'
        ),
    )

    result = requirement.run({"raw_requirement": "anything"})

    assert result["llm_mode"] == "live"
    assert result["normalized_spec"] == "normalized"


def test_extracts_json_wrapped_in_markdown_fence(monkeypatch):
    monkeypatch.setattr(requirement, "is_live", lambda: True)
    monkeypatch.setattr(
        requirement,
        "call_llm",
        lambda *a, **k: (
            '```json\n{"requirement_summary": "s", "identified_ambiguities": [], '
            '"normalized_spec": "n"}\n```'
        ),
    )

    result = requirement.run({"raw_requirement": "anything"})

    assert result["llm_mode"] == "live"
    assert result["normalized_spec"] == "n"

from orchestrator.agents import planning


def test_default_task_graph_is_valid():
    graph = planning.default_task_graph("some normalized spec")
    valid, detail = planning.validate_task_graph(graph)

    assert valid is True, detail


def test_validate_task_graph_rejects_empty():
    valid, detail = planning.validate_task_graph({"tasks": []})
    assert valid is False
    assert "no tasks" in detail


def test_validate_task_graph_rejects_duplicate_ids():
    graph = {
        "tasks": [
            {"id": "a", "description": "x", "depends_on": []},
            {"id": "a", "description": "y", "depends_on": []},
        ]
    }
    valid, detail = planning.validate_task_graph(graph)
    assert valid is False
    assert "duplicate" in detail


def test_validate_task_graph_rejects_unknown_dependency():
    graph = {"tasks": [{"id": "a", "description": "x", "depends_on": ["missing"]}]}
    valid, detail = planning.validate_task_graph(graph)
    assert valid is False
    assert "unknown task" in detail


def test_validate_task_graph_rejects_cycle():
    graph = {
        "tasks": [
            {"id": "a", "description": "x", "depends_on": ["b"]},
            {"id": "b", "description": "y", "depends_on": ["a"]},
        ]
    }
    valid, detail = planning.validate_task_graph(graph)
    assert valid is False
    assert "no root task" in detail or "cycle" in detail


def test_validate_task_graph_rejects_cycle_with_a_root():
    graph = {
        "tasks": [
            {"id": "root", "description": "r", "depends_on": []},
            {"id": "a", "description": "x", "depends_on": ["root", "b"]},
            {"id": "b", "description": "y", "depends_on": ["a"]},
        ]
    }
    valid, detail = planning.validate_task_graph(graph)
    assert valid is False
    assert "cycle" in detail


def test_run_uses_heuristic_when_offline(monkeypatch):
    monkeypatch.setattr(planning, "is_live", lambda: False)

    result = planning.run({"normalized_spec": "Add vanity aliases."})

    assert result["llm_mode"] == "mock"
    [entry] = result["gate_log"]
    assert entry["gate_id"] == "gate_1"
    assert entry["passed"] is True


def test_run_falls_back_when_live_call_raises(monkeypatch):
    monkeypatch.setattr(planning, "is_live", lambda: True)
    monkeypatch.setattr(
        planning, "call_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    result = planning.run({"normalized_spec": "Add vanity aliases."})

    assert result["llm_mode"] == "mock"
    task_ids = {t["id"] for t in result["task_graph"]["tasks"]}
    assert "design" in task_ids


def test_run_falls_back_when_live_call_returns_invalid_graph(monkeypatch):
    monkeypatch.setattr(planning, "is_live", lambda: True)
    monkeypatch.setattr(planning, "call_llm", lambda *a, **k: '{"tasks": []}')

    result = planning.run({"normalized_spec": "Add vanity aliases."})

    assert result["llm_mode"] == "mock"
    task_ids = {t["id"] for t in result["task_graph"]["tasks"]}
    assert "design" in task_ids


def test_run_omits_llm_mode_when_live_call_succeeds(monkeypatch):
    monkeypatch.setattr(planning, "is_live", lambda: True)
    monkeypatch.setattr(
        planning,
        "call_llm",
        lambda *a, **k: (
            '{"tasks": [{"id": "a", "description": "x", "depends_on": []}]}'
        ),
    )

    result = planning.run({"normalized_spec": "spec"})

    # A successful live call must not touch state["llm_mode"] at all — the
    # graph relies on absent keys to mean "unchanged", so this node must
    # never downgrade (or fabricate an upgrade of) another node's flag.
    assert "llm_mode" not in result

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.api_v1.endpoints.traceability import rules as rules_api
from app.services.traceability.engine.nodes.commit_source import CommitSourceExecutor
from app.services.traceability.engine.nodes.create_link_action import CreateLinkActionExecutor
from app.services.traceability.engine.nodes.decision_node import DecisionNodeExecutor
from app.services.traceability.engine.nodes.filter_node import FilterNodeExecutor
from app.services.traceability.engine.nodes.jira_key_extractor import JiraKeyExtractorExecutor
from app.tasks import traceability_tasks


class _ContextStub:
    def __init__(self, input_artifacts, edges):
        self._input_artifacts = input_artifacts
        self.edges = edges
        self.node_outputs = {}
        self.warnings = []

    def get_input_artifacts(self, _node_id):
        return self._input_artifacts

    def set_node_output(self, key, artifacts):
        self.node_outputs[key] = artifacts

    def set_node_output_with_handle(self, node_id, handle, artifacts):
        self.node_outputs[f"{node_id}_{handle}"] = artifacts

    def add_warning(self, message: str):
        self.warnings.append(message)


class _FakeDBSession:
    def __init__(self, rules):
        self._rules = rules
        self.committed = False

    def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self._rules))

    def commit(self):
        self.committed = True


class _FakeSessionFactory:
    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def test_commit_source_alias_mapping():
    executor = CommitSourceExecutor()

    normalized = executor._normalize_filters(
        {"after_date": "2026-01-01", "before_date": "2026-01-31"}
    )

    assert normalized["date_from"] == "2026-01-01"
    assert normalized["date_to"] == "2026-01-31"


def test_jira_key_extractor_alias_mapping():
    executor = JiraKeyExtractorExecutor()

    normalized = executor._normalize_search_fields(["branch_name", "body", "message"])
    assert normalized == ["branch", "description", "message"]

    artifact = SimpleNamespace(
        type="commit", meta={"branch": "main", "description": "POH-12"}, title=None
    )
    assert executor._get_field_value(artifact, "branch_name") == "main"
    assert executor._get_field_value(artifact, "body") == "POH-12"


def test_filter_node_reads_model_fields_before_meta():
    executor = FilterNodeExecutor()
    artifact = SimpleNamespace(
        status="Done",
        title="Primary title",
        meta={"status": "To Do", "title": "Meta title", "custom": "meta-value"},
    )

    assert executor._get_field_value(artifact, "status") == "Done"
    assert executor._get_field_value(artifact, "title") == "Primary title"
    assert executor._get_field_value(artifact, "custom") == "meta-value"


def test_decision_confidence_threshold_routes_per_artifact():
    decision = DecisionNodeExecutor()
    artifacts = [
        SimpleNamespace(id=1, meta={"confidence": 0.9}),
        SimpleNamespace(id=2, meta={"confidence": 0.5}),
        SimpleNamespace(id=3, meta={}),  # Missing confidence should route to FALSE branch.
    ]
    context = _ContextStub(
        input_artifacts=artifacts,
        edges=[
            {"source": "decision_1", "sourceHandle": "true"},
            {"source": "decision_1", "sourceHandle": "false"},
        ],
    )

    decision.execute(
        {
            "id": "decision_1",
            "data": {"config": {"condition_type": "confidence_threshold", "threshold": 80}},
        },
        context,
    )

    true_ids = [artifact.id for artifact in context.node_outputs["decision_1_true"]]
    false_ids = [artifact.id for artifact in context.node_outputs["decision_1_false"]]

    assert true_ids == [1]
    assert false_ids == [2, 3]
    assert [artifact.id for artifact in context.node_outputs["decision_1"]] == [1, 2, 3]


def test_create_link_action_prefers_configured_reverse_link_type():
    executor = CreateLinkActionExecutor()

    configured_value, used_fallback = executor._resolve_reverse_link_type(
        "implements", "custom_reverse"
    )
    fallback_value, used_fallback_for_default = executor._resolve_reverse_link_type(
        "implements", None
    )

    assert configured_value == "custom_reverse"
    assert used_fallback is False
    assert fallback_value == "implemented_by"
    assert used_fallback_for_default is True


def test_create_link_action_single_input_requires_opt_in_for_self_links():
    executor = CreateLinkActionExecutor()
    warnings: list[str] = []
    context = SimpleNamespace(
        incoming_edges={"action_1": [{"source": "source_1"}]},
        get_input_artifacts=lambda _node_id: [
            SimpleNamespace(id=1, external_id="A"),
            SimpleNamespace(id=2, external_id="B"),
        ],
        add_warning=warnings.append,
        add_error=lambda _message: None,
        db=MagicMock(),
        add_link=lambda _link: None,
        rule_id=123,
        node_outputs={},
    )

    executor.execute(
        {
            "id": "action_1",
            "data": {"config": {"link_type": "implements"}},
        },
        context,
    )

    assert warnings
    assert "single-input self-linking is disabled by default" in warnings[0]
    context.db.query.assert_not_called()


def test_create_link_action_single_input_with_opt_in_creates_links():
    executor = CreateLinkActionExecutor()
    context = SimpleNamespace(
        incoming_edges={"action_1": [{"source": "source_1"}]},
        get_input_artifacts=lambda _node_id: [
            SimpleNamespace(id=1, external_id="A"),
            SimpleNamespace(id=2, external_id="B"),
            SimpleNamespace(id=3, external_id="C"),
        ],
        add_warning=lambda _message: None,
        add_error=lambda _message: None,
        db=MagicMock(),
        add_link=lambda _link: None,
        rule_id=123,
        node_outputs={},
    )

    with patch.object(executor, "_create_link") as create_link:
        executor.execute(
            {
                "id": "action_1",
                "data": {"config": {"link_type": "implements", "allow_self_linking": True}},
            },
            context,
        )

    # 3 artifacts => 3 pairwise links when self-linking is enabled
    assert create_link.call_count == 3


def test_decision_validation_threshold_range():
    node = SimpleNamespace(
        id="decision_1",
        type="decisionNode",
        data={
            "label": "Decision",
            "config": {"condition_type": "confidence_threshold", "threshold": 101},
        },
    )

    errors, _warnings = rules_api._validate_node_configuration(node)

    assert errors
    assert "between 0 and 100" in errors[0].message


def test_scheduler_uses_schedule_fields_and_recomputes_next_run(monkeypatch):
    now = datetime.now(timezone.utc)
    rule = SimpleNamespace(
        id=42,
        name="scheduled rule",
        schedule_cron="*/5 * * * *",
        schedule_enabled=True,
        enabled=True,
        next_scheduled_run=now - timedelta(minutes=1),
    )
    db = _FakeDBSession([rule])
    session_factory = _FakeSessionFactory(db)
    executed_rule_ids = []

    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    monkeypatch.setattr(
        traceability_tasks.execute_rule_task,
        "delay",
        lambda rule_id: executed_rule_ids.append(rule_id),
    )

    result = traceability_tasks.scheduled_rule_execution_task()

    assert result["rules_checked"] == 1
    assert len(result["rules_executed"]) == 1
    assert executed_rule_ids == [42]
    assert db.committed is True
    assert rule.next_scheduled_run is not None
    assert rule.next_scheduled_run > now


def test_scheduler_disables_invalid_cron_to_avoid_error_loop(monkeypatch):
    rule = SimpleNamespace(
        id=77,
        name="bad cron rule",
        schedule_cron="bad cron value",
        schedule_enabled=True,
        enabled=True,
        next_scheduled_run=datetime.now(timezone.utc),
    )
    db = _FakeDBSession([rule])
    session_factory = _FakeSessionFactory(db)

    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    monkeypatch.setattr(traceability_tasks.execute_rule_task, "delay", MagicMock())

    result = traceability_tasks.scheduled_rule_execution_task()

    assert result["rules_checked"] == 1
    assert result["rules_executed"] == []
    assert db.committed is True
    assert rule.schedule_enabled is False
    assert rule.next_scheduled_run is None

"""Testes unitários determinísticos da Tool Layer, sem LLM ou API externa."""

from __future__ import annotations

import inspect
import json
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from app.integrations.tractian_client import (
    ClientResult,
    EvidenceStatus,
    OperationKind,
    RequestContext,
    TractianClient,
)
from app.tools import ExecutionPolicy, ToolExposure, get_action_tools, get_investigator_tools
from app.tools.registry import inspect_tool_surface
from app.tools.schemas import (
    AnalysisActionInput,
    AssetConfigUpdateInput,
    AssetIdInput,
    AssetPointInput,
    KnowledgeSearchInput,
)


READ_CASES = (
    ("get_asset_context", "get_asset", {"asset_id": "asset_1"}, ("asset_1",), {}),
    (
        "list_asset_analyses",
        "list_asset_analyses",
        {"asset_id": "asset_1", "status": "current"},
        ("asset_1",),
        {"status": "current"},
    ),
    ("get_analysis_details", "get_analysis", {"analysis_id": "an_1"}, ("an_1",), {}),
    (
        "get_asset_baseline",
        "get_baseline",
        {"asset_id": "asset_1", "point_id": "point_1"},
        ("asset_1",),
        {"point_id": "point_1"},
    ),
    ("get_asset_rms", "get_rms", {"asset_id": "asset_1"}, ("asset_1",), {"point_id": None}),
    (
        "get_asset_spectrum",
        "get_spectrum",
        {"asset_id": "asset_1", "point_id": "point_1"},
        ("asset_1",),
        {"point_id": "point_1"},
    ),
    (
        "get_asset_data_quality",
        "get_data_quality",
        {"asset_id": "asset_1"},
        ("asset_1",),
        {"point_id": None},
    ),
    ("get_model_capabilities", "get_model", {"model_id": "model_1"}, ("model_1",), {}),
    (
        "search_industrial_knowledge",
        "search_knowledge",
        {"query": "falha de rolamento", "knowledge_type": "procedure"},
        ("falha de rolamento",),
        {"knowledge_type": "procedure"},
    ),
    (
        "get_knowledge_document",
        "get_knowledge_document",
        {"doc_id": "doc_1"},
        ("doc_1",),
        {},
    ),
)


ACTION_CASES = (
    (
        "request_asset_config_update",
        "update_asset_config",
        {
            "asset_id": "asset_1",
            "changes": {"criticality": "high"},
            "justification": "Mudança aprovada pela manutenção.",
        },
        ("asset_1",),
        {"changes": {"criticality": "high"}, "justification": "Mudança aprovada pela manutenção."},
    ),
    (
        "request_analysis_reprocessing",
        "reprocess_analysis",
        {
            "analysis_id": "an_1",
            "justification": "Novos dados foram coletados no ativo.",
            "params": {"source": "maintenance"},
        },
        ("an_1",),
        {
            "justification": "Novos dados foram coletados no ativo.",
            "params": {"source": "maintenance"},
        },
    ),
    (
        "request_specialist_analysis",
        "request_specialist_analysis",
        {"analysis_id": "an_1", "justification": "O resultado permanece tecnicamente inconclusivo."},
        ("an_1",),
        {"justification": "O resultado permanece tecnicamente inconclusivo.", "params": None},
    ),
    (
        "request_model_retraining",
        "request_model_retraining",
        {"model_id": "model_1", "justification": "Cobertura insuficiente confirmada para este ativo."},
        ("model_1",),
        {"justification": "Cobertura insuficiente confirmada para este ativo.", "params": None},
    ),
    (
        "request_case_escalation",
        "escalate_case",
        {"case_id": "case_1", "justification": "O caso requer inspeção humana presencial."},
        ("case_1",),
        {"justification": "O caso requer inspeção humana presencial.", "params": None},
    ),
)


def _tool_by_name(name: str):
    return next(tool for tool in (*get_investigator_tools(), *get_action_tools()) if tool.name == name)


@pytest.mark.parametrize(("tool_name", "client_method", "arguments", "args", "kwargs"), READ_CASES)
def test_each_read_tool_calls_only_its_client_operation(
    tool_name: str,
    client_method: str,
    arguments: dict[str, object],
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    client = Mock(spec=TractianClient)
    expected = Mock(spec=ClientResult)
    getattr(client, client_method).return_value = expected

    result = _tool_by_name(tool_name).invoke(client, arguments)

    assert result is expected
    getattr(client, client_method).assert_called_once_with(*args, **kwargs)
    assert sum(method.call_count for method in (getattr(client, name) for name in TractianClient.OPERATIONS)) == 1


@pytest.mark.parametrize(("tool_name", "client_method", "arguments", "args", "kwargs"), ACTION_CASES)
def test_each_action_capability_calls_only_its_client_operation(
    tool_name: str,
    client_method: str,
    arguments: dict[str, object],
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    client = Mock(spec=TractianClient)
    expected = Mock(spec=ClientResult)
    getattr(client, client_method).return_value = expected

    result = _tool_by_name(tool_name).invoke(client, arguments)

    assert result is expected
    getattr(client, client_method).assert_called_once_with(*args, **kwargs)


@pytest.mark.parametrize("status", list(EvidenceStatus))
def test_tool_preserves_every_semantic_status(status: EvidenceStatus) -> None:
    expected = ClientResult(
        operation="get_asset",
        operation_kind=OperationKind.READ,
        method="GET",
        path="/assets/asset_1",
        transport_ok=True,
        status_code=200,
        evidence_status=status,
        data={"id": "asset_1"},
    )
    client = Mock(spec=TractianClient)
    client.get_asset.return_value = expected

    result = _tool_by_name("get_asset_context").invoke(client, {"asset_id": "asset_1"})

    assert result is expected
    assert result.evidence_status is status


@pytest.mark.parametrize("forbidden", ["user_id", "x_user_id", "headers", "credentials"])
def test_identity_and_transport_fields_are_absent_and_rejected(forbidden: str) -> None:
    for tool in (*get_investigator_tools(), *get_action_tools()):
        assert forbidden not in tool.input_schema.model_fields

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AssetIdInput.model_validate({"asset_id": "asset_1", forbidden: "attacker-controlled"})


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (AssetIdInput, {"asset_id": "  "}),
        (AssetPointInput, {"asset_id": "asset_1", "point_id": ""}),
        (KnowledgeSearchInput, {"query": "", "knowledge_type": "procedure"}),
        (KnowledgeSearchInput, {"query": "bearing", "knowledge_type": "unknown"}),
        (
            AssetConfigUpdateInput,
            {"asset_id": "asset_1", "changes": {"criticality": "invalid"}, "justification": "x" * 30},
        ),
        (
            AssetConfigUpdateInput,
            {"asset_id": "asset_1", "changes": {"rpm": 1000}, "justification": "x" * 30},
        ),
        (AnalysisActionInput, {"analysis_id": "an_1", "justification": "curta"}),
    ],
)
def test_schemas_reject_invalid_inputs(schema: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_request_context_remains_bound_to_client_and_outside_tool_arguments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-user-id"] == "usr_system"
        return httpx.Response(200, json={"accepted": True, "action_id": "act_1", "message": "Aceito."})

    with TractianClient(
        RequestContext(user_id="usr_system"),
        base_url="https://tractian.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = _tool_by_name("request_analysis_reprocessing").invoke(
            client,
            {"analysis_id": "an_1", "justification": "Há novas medições disponíveis para análise."},
        )

    assert result.transport_ok is True


def test_registry_has_exactly_the_approved_surface() -> None:
    investigator = get_investigator_tools()
    actions = get_action_tools()

    assert len(investigator) == 10
    assert len(actions) == 5
    assert len({tool.name for tool in (*investigator, *actions)}) == 15
    assert all(tool.operation_kind is OperationKind.READ for tool in investigator)
    assert all(tool.exposure is ToolExposure.INVESTIGATOR for tool in investigator)
    assert all(tool.execution_policy is ExecutionPolicy.UNRESTRICTED for tool in investigator)
    assert all(tool.operation_kind is OperationKind.ACTION for tool in actions)
    assert all(tool.exposure is ToolExposure.CATALOG_ONLY for tool in actions)
    assert all(tool.execution_policy is ExecutionPolicy.FUTURE_POLICY_REQUIRED for tool in actions)


def test_internal_operations_never_appear_as_tools() -> None:
    operations = {tool.client_operation for tool in (*get_investigator_tools(), *get_action_tools())}
    names = {tool.name for tool in (*get_investigator_tools(), *get_action_tools())}

    assert "get_current_user" not in operations
    assert "get_company" not in operations
    assert "list_company_assets" not in operations
    assert "resolve_company_context" not in names


def test_ambiguous_capabilities_have_distinct_names_schemas_and_descriptions() -> None:
    pairs = (
        ("list_asset_analyses", "get_analysis_details"),
        ("get_asset_rms", "get_asset_spectrum"),
        ("get_asset_baseline", "get_asset_data_quality"),
        ("get_model_capabilities", "request_model_retraining"),
        ("search_industrial_knowledge", "get_knowledge_document"),
    )

    for left_name, right_name in pairs:
        left, right = _tool_by_name(left_name), _tool_by_name(right_name)
        assert left.name != right.name
        assert left.description != right.description
        assert left.client_operation != right.client_operation


def test_inspection_is_deterministic_complete_and_json_serializable() -> None:
    first = inspect_tool_surface()
    second = inspect_tool_surface()

    assert first == second
    assert len(first) == 15
    assert set(first[0]) == {
        "name",
        "category",
        "read_action",
        "description",
        "input_schema",
        "client_operation",
        "exposure",
        "execution_policy",
    }
    assert json.loads(json.dumps(first, ensure_ascii=False)) == first


def test_public_invocation_signature_has_no_context_or_identity_argument() -> None:
    parameters = set(inspect.signature(type(get_investigator_tools()[0]).invoke).parameters)
    assert parameters == {"self", "client", "arguments"}
    assert parameters.isdisjoint({"user_id", "headers", "credentials", "request_context"})

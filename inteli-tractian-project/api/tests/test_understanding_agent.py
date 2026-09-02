"""Testes do Understanding Agent: schema, prompt, parsing e limites de escopo.

Nenhum teste deste arquivo consome API externa.
"""

from __future__ import annotations

import ast
import inspect
import re
from datetime import datetime, timezone
from types import ModuleType

import pytest
from pydantic import ValidationError

from app.agents.understanding import agent as agent_module
from app.agents.understanding import prompts as prompts_module
from app.agents.understanding import schemas as schemas_module
from app.agents.understanding.agent import (
    OUTPUT_JSON_SCHEMA,
    UnderstandingAgent,
    understand_request,
)
from app.agents.understanding.observability import (
    AgentComponent,
    AgentInvocationLog,
    AgentInvocationRecord,
    AgentInvocationStatus,
)
from app.agents.understanding.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.agents.understanding.provider import (
    APPROVED_MODEL_BASE,
    MODEL_CANDIDATES,
    MODEL_SELECTION_STATUS,
    ModelSelectionBlocked,
    resolve_structured_provider,
)
from app.agents.understanding.schemas import (
    Constraints,
    UnderstandingInput,
    UnderstandingOutput,
)
from tests.understanding_fakes import FailingProvider, RecordingProvider


VALID_OUTPUT: dict[str, object] = {
    "request_class": "investigate",
    "intents": [
        {
            "intent_id": "intent_1",
            "kind": "investigative",
            "summary": "Avaliar mudança de vibração.",
            "target_entities": ["asset_B211"],
            "requested_outcome": "Resposta fundamentada.",
        }
    ],
    "questions": [
        {
            "question_id": "q1",
            "text": "O desvio é real?",
            "kind": "diagnosis",
            "depends_on": [],
        }
    ],
    "entities": {
        "assets": ["asset_B211"],
        "analyses": [],
        "models": [],
        "technical_terms": ["vibração RMS"],
        "temporal_references": ["nesta semana"],
    },
    "investigation_targets": ["asset context", "baseline", "data quality"],
    "missing_information": [],
    "requested_actions": [],
    "constraints": {
        "tenant_scope_known": True,
        "permissions_known": True,
        "action_execution_allowed": False,
    },
    "confidence": 0.9,
}


def _imported_modules(module: ModuleType) -> set[str]:
    """Módulos efetivamente importados, ignorando docstrings e comentários."""

    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _referenced_names(module: ModuleType) -> set[str]:
    """Identificadores usados no código, ignorando docstrings e comentários."""

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
            if isinstance(node, ast.ImportFrom) and node.module:
                names.update(node.module.split("."))
    return names


@pytest.fixture
def request_input() -> UnderstandingInput:
    return UnderstandingInput.model_validate(
        {
            "message": "A vibração RMS do asset_B211 subiu nesta semana. Isso é desvio real?",
            "available_context": {
                "tenant_ref": "tenant_syn_dev_01",
                "asset_refs": ["asset_B211"],
                "role": "operator",
                "permissions": ["read"],
            },
        }
    )


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def test_output_schema_accepts_approved_contract() -> None:
    output = UnderstandingOutput.model_validate(VALID_OUTPUT)
    assert output.request_class.value == "investigate"
    assert output.constraints.action_execution_allowed is False


def test_output_schema_rejects_extra_fields() -> None:
    payload = {**VALID_OUTPUT, "reasoning": "porque sim"}
    with pytest.raises(ValidationError) as error:
        UnderstandingOutput.model_validate(payload)
    assert any(item["type"] == "extra_forbidden" for item in error.value.errors())


def test_output_schema_rejects_nested_extra_fields() -> None:
    payload = {
        **VALID_OUTPUT,
        "constraints": {**VALID_OUTPUT["constraints"], "confidence_score": 0.5},
    }
    with pytest.raises(ValidationError):
        UnderstandingOutput.model_validate(payload)


def test_output_schema_rejects_missing_required_field() -> None:
    payload = {key: value for key, value in VALID_OUTPUT.items() if key != "entities"}
    with pytest.raises(ValidationError):
        UnderstandingOutput.model_validate(payload)


def test_action_execution_allowed_cannot_be_true() -> None:
    """A permissão de execução é estruturalmente impossível de declarar."""

    with pytest.raises(ValidationError):
        Constraints(
            tenant_scope_known=True,
            permissions_known=True,
            action_execution_allowed=True,
        )


def test_output_is_frozen() -> None:
    output = UnderstandingOutput.model_validate(VALID_OUTPUT)
    with pytest.raises(ValidationError):
        output.confidence = 0.1


def test_no_confidence_score_or_certainty_aliases() -> None:
    """`confidence` existe por paridade com o schema aprovado; nenhuma segunda
    camada de confiança foi introduzida."""

    fields = set(UnderstandingOutput.model_fields)
    assert "confidence" in fields
    assert {"confidence_score", "certainty", "confidence_level"} & fields == set()


def test_schema_mirrors_approved_contract_fields() -> None:
    approved = {
        "request_class",
        "intents",
        "questions",
        "entities",
        "investigation_targets",
        "missing_information",
        "requested_actions",
        "constraints",
        "confidence",
    }
    assert set(UnderstandingOutput.model_fields) == approved


def test_output_json_schema_is_usable_for_structured_output() -> None:
    assert OUTPUT_JSON_SCHEMA["type"] == "object"
    assert OUTPUT_JSON_SCHEMA["additionalProperties"] is False
    assert set(OUTPUT_JSON_SCHEMA["required"]) == set(UnderstandingOutput.model_fields)


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #


def test_prompt_is_versioned() -> None:
    assert PROMPT_VERSION == "understanding_prompt_v1"
    assert UnderstandingAgent.prompt_version == PROMPT_VERSION


def test_prompt_forbids_investigation_and_action(request_input: UnderstandingInput) -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "não chama tools" in lowered
    assert "não executa nenhuma ação" in lowered
    assert "não diagnostica" in lowered
    assert "sempre `false`" in lowered


def test_prompt_contains_no_dataset_examples() -> None:
    """O baseline é prompt-only: nenhum sample id, nenhum asset de split."""

    assert "syn_u_" not in SYSTEM_PROMPT
    assert "syn_i_" not in SYSTEM_PROMPT
    for asset in ("asset_B211", "asset_S425", "asset_X216", "asset_H110", "asset_F115"):
        assert asset not in SYSTEM_PROMPT


def test_prompt_contains_no_concrete_resource_identifier() -> None:
    """Nenhum id concreto — nem sintético, nem do Golden Set — no prompt."""

    # Um id concreto tem prefixo de recurso e ao menos um dígito no sufixo;
    # `asset_id` e `asset_refs` são nomes de campo do schema, não recursos.
    leaked = re.findall(
        r"\b(?:asset|an|mdl|tenant)_[A-Za-z0-9_]*\d[A-Za-z0-9_]*\b", SYSTEM_PROMPT
    )
    leaked += re.findall(r"\b(?:comp|kb|case_tkt)_[A-Za-z0-9_]+\b", SYSTEM_PROMPT)
    assert leaked == [], f"Identificadores concretos no prompt: {leaked}"
    for golden in ("TKT-INV", "TKT-CTX", "TKT-EXE", "an_9906", "kb_proc_001"):
        assert golden not in SYSTEM_PROMPT


def test_prompt_module_does_not_import_dataset_layer() -> None:
    assert _imported_modules(prompts_module) == {
        "__future__",
        "json",
        "typing",
        "app.agents.understanding.schemas",
    }


def test_user_prompt_serializes_only_message_and_context(
    request_input: UnderstandingInput,
) -> None:
    prompt = build_user_prompt(request_input)
    assert request_input.message in prompt
    assert "tenant_syn_dev_01" in prompt
    assert "asset_B211" in prompt
    assert "expected" not in prompt
    assert "target" not in prompt


def test_user_prompt_is_deterministic(request_input: UnderstandingInput) -> None:
    assert build_user_prompt(request_input) == build_user_prompt(request_input)


# --------------------------------------------------------------------------- #
# Agente
# --------------------------------------------------------------------------- #


def test_agent_parses_structured_output(request_input: UnderstandingInput) -> None:
    provider = RecordingProvider([VALID_OUTPUT])
    invocation = UnderstandingAgent(provider, trace_id="trace-1").understand_request(request_input)

    assert invocation.ok
    assert invocation.schema_valid
    assert invocation.output is not None
    assert invocation.output.request_class.value == "investigate"
    assert invocation.record.status is AgentInvocationStatus.COMPLETED
    assert invocation.record.component is AgentComponent.UNDERSTANDING
    assert invocation.record.prompt_version == PROMPT_VERSION
    assert invocation.record.model_id == "fake-model-v0"
    assert invocation.record.usage.total_tokens == 150
    assert invocation.record.duration_ms >= 0
    assert invocation.record.output is not None


def test_agent_sends_system_prompt_and_schema(request_input: UnderstandingInput) -> None:
    provider = RecordingProvider([VALID_OUTPUT])
    UnderstandingAgent(provider, trace_id="trace-1").understand_request(request_input)

    call = provider.calls[0]
    assert call["system_prompt"] == SYSTEM_PROMPT
    assert call["json_schema"] == OUTPUT_JSON_SCHEMA


def test_agent_records_invalid_output_without_inventing_values(
    request_input: UnderstandingInput,
) -> None:
    broken = {**VALID_OUTPUT, "request_class": "diagnosticar"}
    invocation = UnderstandingAgent(
        RecordingProvider([broken]), trace_id="trace-1"
    ).understand_request(request_input)

    assert not invocation.ok
    assert not invocation.schema_valid
    assert invocation.output is None
    assert invocation.record.status is AgentInvocationStatus.INVALID_OUTPUT
    assert invocation.record.output is None
    assert invocation.record.failure is not None
    assert "request_class" in invocation.record.failure.message
    assert invocation.raw_content == broken


def test_agent_rejects_extra_field_from_model(request_input: UnderstandingInput) -> None:
    payload = {**VALID_OUTPUT, "confidence_score": 0.4}
    invocation = UnderstandingAgent(
        RecordingProvider([payload]), trace_id="trace-1"
    ).understand_request(request_input)

    assert invocation.record.status is AgentInvocationStatus.INVALID_OUTPUT
    assert "confidence_score" in invocation.record.failure.message


def test_agent_rejects_free_text_output(request_input: UnderstandingInput) -> None:
    invocation = UnderstandingAgent(
        RecordingProvider(["Claro! Aqui está o JSON: {...}"]), trace_id="trace-1"
    ).understand_request(request_input)

    assert invocation.record.status is AgentInvocationStatus.INVALID_OUTPUT
    assert invocation.output is None


def test_agent_does_not_retry_on_invalid_output(request_input: UnderstandingInput) -> None:
    provider = RecordingProvider([{"request_class": "investigate"}])
    UnderstandingAgent(provider, trace_id="trace-1").understand_request(request_input)
    assert len(provider.calls) == 1


def test_agent_records_provider_error(request_input: UnderstandingInput) -> None:
    invocation = UnderstandingAgent(
        FailingProvider(), trace_id="trace-1"
    ).understand_request(request_input)

    assert invocation.record.status is AgentInvocationStatus.PROVIDER_ERROR
    assert invocation.record.output is None
    assert invocation.record.failure is not None
    assert "provedor indisponível" not in invocation.record.failure.message


def test_agent_never_receives_tools_client_or_executor() -> None:
    """Isolamento por construção: o agente não tem como chamar a API."""

    parameters = set(inspect.signature(UnderstandingAgent.__init__).parameters)
    assert parameters == {
        "self",
        "provider",
        "trace_id",
        "clock",
        "monotonic_clock",
        "invocation_id_factory",
    }

    referenced = _referenced_names(agent_module)
    for forbidden in (
        "TractianClient",
        "TrackedToolExecutor",
        "ToolDefinition",
        "EvidenceLedger",
        "EvidenceRecord",
        "INVESTIGATOR_TOOLS",
        "httpx",
        "invoke",
        "execute",
    ):
        assert forbidden not in referenced, f"{forbidden} não pode aparecer no agente."


def test_understanding_package_does_not_import_tool_or_ledger_layers() -> None:
    from app.agents.understanding import dataset, metrics, observability, provider, runner

    for module in (
        agent_module,
        schemas_module,
        prompts_module,
        dataset,
        metrics,
        observability,
        provider,
        runner,
    ):
        for imported in _imported_modules(module):
            assert not imported.startswith("app.tools"), module.__name__
            assert not imported.startswith("app.integrations"), module.__name__
            assert imported != "app.observability.ledger", module.__name__
            assert imported != "app.observability.executor", module.__name__


def test_agent_invocation_ids_are_sequential(request_input: UnderstandingInput) -> None:
    agent = UnderstandingAgent(RecordingProvider([VALID_OUTPUT]), trace_id="trace-1")
    first = agent.understand_request(request_input).record
    second = agent.understand_request(request_input).record
    assert first.invocation_id == "trace-1:agent:000001"
    assert second.invocation_id == "trace-1:agent:000002"


def test_facade_understand_request(request_input: UnderstandingInput) -> None:
    invocation = understand_request(
        request_input, provider=RecordingProvider([VALID_OUTPUT]), trace_id="trace-9"
    )
    assert invocation.ok
    assert invocation.record.trace_id == "trace-9"


# --------------------------------------------------------------------------- #
# Instrumentação
# --------------------------------------------------------------------------- #


def _record(**overrides: object) -> AgentInvocationRecord:
    moment = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "trace_id": "trace-1",
        "invocation_id": "trace-1:agent:000001",
        "sequence": 1,
        "component": AgentComponent.UNDERSTANDING,
        "model_id": "fake-model-v0",
        "prompt_version": PROMPT_VERSION,
        "started_at": moment,
        "completed_at": moment,
        "duration_ms": 1.0,
        "status": AgentInvocationStatus.COMPLETED,
        "input": {"message": "oi"},
    }
    payload.update(overrides)
    return AgentInvocationRecord(**payload)


def test_invocation_record_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        _record(started_at=datetime(2026, 9, 2, 12, 0, 0))


def test_invocation_record_has_no_chain_of_thought_field() -> None:
    fields = set(AgentInvocationRecord.model_fields)
    assert {"reasoning", "chain_of_thought", "thinking", "rationale"} & fields == set()
    assert "output" in fields and "input" in fields


def test_invocation_log_assigns_sequence_and_rejects_other_trace() -> None:
    log = AgentInvocationLog("trace-1")
    assert log.append(_record()).sequence == 1
    assert log.append(_record()).sequence == 2
    with pytest.raises(ValueError):
        log.append(_record(trace_id="trace-2"))


def test_invocation_log_is_serializable() -> None:
    log = AgentInvocationLog("trace-1")
    log.append(_record())
    dumped = log.as_dicts()
    assert dumped[0]["component"] == "understanding_agent"
    assert dumped[0]["prompt_version"] == PROMPT_VERSION


def test_understanding_does_not_produce_evidence_records() -> None:
    from app.agents.understanding import observability, runner

    for module in (observability, runner, agent_module):
        assert "EvidenceRecord" not in _referenced_names(module)
        assert "EvidenceLedger" not in _referenced_names(module)


# --------------------------------------------------------------------------- #
# Seleção de modelo
# --------------------------------------------------------------------------- #


def test_no_model_base_is_approved() -> None:
    assert APPROVED_MODEL_BASE is None
    assert MODEL_SELECTION_STATUS == "BLOCKED_MODEL_SELECTION"


def test_resolve_provider_blocks_instead_of_choosing() -> None:
    with pytest.raises(ModelSelectionBlocked) as error:
        resolve_structured_provider()
    assert "BLOCKED_MODEL_SELECTION" in str(error.value)


def test_model_candidates_are_documented() -> None:
    assert len(MODEL_CANDIDATES) >= 2
    assert {candidate.provider for candidate in MODEL_CANDIDATES} >= {
        "anthropic",
        "openai_compatible",
    }


def test_provider_module_does_not_read_credentials() -> None:
    from app.agents.understanding import provider as provider_module

    source = inspect.getsource(provider_module)
    assert "os.environ" not in source
    assert "getenv" not in source

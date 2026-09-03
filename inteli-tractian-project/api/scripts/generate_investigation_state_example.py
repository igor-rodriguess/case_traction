"""Gera o exemplo versionado do InvestigationState sem IA ou rede."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput
from app.integrations.tractian_client import ClientResult, EvidenceStatus, OperationKind
from app.investigation import (
    InvestigationDecision,
    InvestigationDecisionType,
    ToolRequest,
    UnderstandingSource,
    attach_understanding,
    begin_investigation,
    create_investigation_state,
    record_decision,
    synchronize_observability,
)
from app.observability import TrackedToolExecutor
from app.tools import get_investigator_tools


EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "architecture"
    / "examples"
    / "06-investigation-state-example.json"
)
EXAMPLE_TIME = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)


class DeterministicAssetClient:
    """Fixture local mínima; possui somente a operação READ usada no exemplo."""

    def get_asset(self, asset_id: str) -> ClientResult:
        return ClientResult(
            operation="get_asset",
            operation_kind=OperationKind.READ,
            method="GET",
            path=f"/assets/{asset_id}",
            transport_ok=True,
            status_code=200,
            evidence_status=EvidenceStatus.COMPLETE,
            data={"id": asset_id, "name": "Redutor secundário", "criticality": "high"},
            notes="Fixture determinística; nenhuma API externa foi chamada.",
        )


def _iterator(values: list[object]):
    iterator: Iterator[object] = iter(values)
    return lambda: next(iterator)


def example_request() -> UnderstandingInput:
    return UnderstandingInput.model_validate(
        {
            "message": "A vibração RMS do asset_B211 subiu nesta semana. Isso é desvio real?",
            "available_context": {
                "tenant_ref": "tenant_fixture_01",
                "asset_refs": ["asset_B211"],
                "role": "operator",
                "permissions": ["read"],
            },
        }
    )


def example_understanding() -> UnderstandingOutput:
    return UnderstandingOutput.model_validate(
        {
            "request_class": "investigate",
            "intents": [
                {
                    "intent_id": "intent_1",
                    "kind": "investigative",
                    "summary": "Avaliar aumento de vibração RMS.",
                    "target_entities": ["asset_B211"],
                    "requested_outcome": "Resposta baseada em evidências.",
                }
            ],
            "questions": [
                {
                    "question_id": "question_1",
                    "text": "O aumento representa um desvio real?",
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
            "investigation_targets": ["asset context", "rms trend", "baseline", "data quality"],
            "missing_information": [],
            "requested_actions": [],
            "constraints": {
                "tenant_scope_known": True,
                "permissions_known": True,
                "action_execution_allowed": False,
            },
            "confidence": 0.9,
        }
    )


def build_example_state():
    """Executa o fluxo determinístico coberto pelo teste de integração."""

    runtime = create_investigation_state(
        example_request(),
        case_id="case_fixture_001",
        request_id="request_fixture_001",
        trace_id="trace_fixture_001",
        max_investigation_steps=12,
        max_tool_calls=8,
    )
    state = attach_understanding(
        runtime.state,
        example_understanding(),
        source=UnderstandingSource.TEST_FIXTURE,
    )
    state = begin_investigation(state)
    state = record_decision(
        state,
        InvestigationDecision(
            decision_id="decision_fixture_001",
            type=InvestigationDecisionType.TOOL_CALL,
            reason_codes=("asset_context_required",),
            tool_request=ToolRequest(
                tool_name="get_asset_context",
                arguments={"asset_id": "asset_B211"},
            ),
        ),
    )

    tool = next(tool for tool in get_investigator_tools() if tool.name == "get_asset_context")
    executor = TrackedToolExecutor(
        DeterministicAssetClient(),  # type: ignore[arg-type]
        runtime.trace,
        runtime.evidence_ledger,
        clock=_iterator([EXAMPLE_TIME, EXAMPLE_TIME + timedelta(milliseconds=25)]),
        monotonic_clock=_iterator([10.0, 10.025]),
        call_id_factory=lambda: "call_fixture_001",
        evidence_id_factory=lambda: "evidence_fixture_001",
    )
    executor.execute(tool, state.decision.tool_request.arguments)  # type: ignore[union-attr]
    return synchronize_observability(state, runtime.trace, runtime.evidence_ledger)


def write_example(path: Path = EXAMPLE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_example_state().model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_example())

"""Gera o showcase determinístico da Etapa 06B, sem IA nem rede."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.integrations.tractian_client import ClientResult, EvidenceStatus, OperationKind
from app.investigation import InvestigationDecision, InvestigationDecisionType, ToolRequest, create_investigation_state
from app.observability import TrackedToolExecutor
from app.orchestration import InvestigationGraphDependencies, build_investigation_graph
from scripts.generate_investigation_state_example import example_request, example_understanding


EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "architecture"
    / "examples"
    / "06b-langgraph-skeleton-example.json"
)


class FixtureClient:
    def __init__(self) -> None:
        self._results = deque(
            [
                ("get_asset", {"id": "asset_B211", "criticality": "high"}),
                ("get_rms", {"asset_id": "asset_B211", "trend": "elevated"}),
            ]
        )

    def _result(self) -> ClientResult:
        operation, data = self._results.popleft()
        return ClientResult(
            operation=operation,
            operation_kind=OperationKind.READ,
            method="GET",
            path=f"/assets/asset_B211/{'rms' if operation == 'get_rms' else ''}".rstrip("/"),
            transport_ok=True,
            status_code=200,
            evidence_status=EvidenceStatus.COMPLETE,
            data=data,
            notes="Fixture determinística; nenhuma API externa foi chamada.",
        )

    def get_asset(self, asset_id: str) -> ClientResult:
        return self._result()

    def get_rms(self, asset_id: str, *, point_id: str | None = None) -> ClientResult:
        return self._result()


class FixtureInvestigator:
    def __init__(self) -> None:
        self._decisions = deque(
            [
                InvestigationDecision(
                    decision_id="decision_fixture_001",
                    type=InvestigationDecisionType.TOOL_CALL,
                    reason_codes=("asset_context_required",),
                    tool_request=ToolRequest(tool_name="get_asset_context", arguments={"asset_id": "asset_B211"}),
                ),
                InvestigationDecision(
                    decision_id="decision_fixture_002",
                    type=InvestigationDecisionType.TOOL_CALL,
                    reason_codes=("rms_trend_required",),
                    tool_request=ToolRequest(tool_name="get_asset_rms", arguments={"asset_id": "asset_B211"}),
                ),
                InvestigationDecision(
                    decision_id="decision_fixture_003",
                    type=InvestigationDecisionType.ANSWER,
                    reason_codes=("evidence_collected",),
                    supporting_evidence_ids=("trace_fixture_06b:evidence:000001", "trace_fixture_06b:evidence:000002"),
                ),
            ]
        )

    def __call__(self, _state) -> InvestigationDecision:
        return self._decisions.popleft()


def build_showcase() -> dict[str, object]:
    runtime = create_investigation_state(
        example_request(),
        case_id="case_fixture_06b",
        request_id="request_fixture_06b",
        trace_id="trace_fixture_06b",
    )
    graph_events: list[dict[str, object]] = []

    def observe(node: str, state) -> None:
        graph_events.append(
            {
                "node": node,
                "phase": state.phase.value,
                "decision_type": state.decision.type.value if state.decision else None,
                "tool_call_count": state.tool_call_count,
                "investigation_step_count": state.investigation_step_count,
            }
        )

    started = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    timestamps = iter(
        [
            started,
            started + timedelta(milliseconds=20),
            started + timedelta(milliseconds=40),
            started + timedelta(milliseconds=70),
        ]
    )
    monotonic = iter([10.0, 10.02, 20.0, 20.03])
    executor = TrackedToolExecutor(  # type: ignore[arg-type]
        FixtureClient(),
        runtime.trace,
        runtime.evidence_ledger,
        clock=lambda: next(timestamps),
        monotonic_clock=lambda: next(monotonic),
    )
    graph = build_investigation_graph(
        InvestigationGraphDependencies(
            runtime=runtime,
            understanding=lambda _: example_understanding(),
            investigator=FixtureInvestigator(),
            tool_executor=executor,
            node_observer=observe,
        )
    )
    state = graph.invoke({"state": runtime.state})["state"]
    return {
        "showcase_type": "deterministic_langgraph_skeleton",
        "understanding_source": "test_fixture",
        "investigator_source": "test_fixture",
        "graph_execution_sequence": graph_events,
        "phase_transitions": [event["phase"] for event in graph_events],
        "state": state.model_dump(mode="json"),
        "final_phase": state.phase.value,
        "final_response": None,
        "human_handoff": None,
    }


def write_showcase(path: Path = EXAMPLE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_showcase(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_showcase())

"""Gera showcase determinístico da Etapa 08 a partir dos contratos versionados."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_langgraph_skeleton_example import EXAMPLE_PATH as GRAPH_EXAMPLE_PATH


EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "examples" / "08-execution-intelligence-example.json"


def build_showcase() -> dict[str, object]:
    graph = json.loads(GRAPH_EXAMPLE_PATH.read_text(encoding="utf-8"))
    state = graph["state"]
    evidence = state["evidence_ledger"]["records"]
    evidence_ids = [item["evidence_id"] for item in evidence]
    claim = {"claim_id": "claim_fixture_08", "statement": "A tendência RMS está elevada; a conclusão é limitada à evidência coletada.", "supporting_evidence_ids": [evidence_ids[1]], "contradictory_evidence_ids": [], "limitation": "Amostra sintética e escopo limitado.", "status": "qualified"}
    plan = {"plan_id": "plan_fixture_08", "objectives": ["Verificar contexto e tendência de RMS."], "investigation_questions": ["A tendência RMS observada merece investigação adicional?"], "suggested_capabilities": [{"name": "get_asset_rms"}, {"name": "get_asset_baseline"}], "dependencies": [], "missing_information": [], "stopping_conditions": ["Evidência suficiente ou limitação explícita."], "reason_codes": ["RMS_DEVIATION"]}
    conclusion = {"conclusion_id": "conclusion_fixture_08", "claims": [claim], "supporting_evidence_ids": evidence_ids, "contradictory_evidence_ids": [], "limitations": ["Amostra sintética e escopo limitado."], "unresolved_points": [], "reason_codes": ["EVIDENCE_COLLECTED"]}
    report = {"report_id": "report_fixture_08", "case_id": state["case_id"], "audience": "tractian_engineering_team", "executive_summary": "Relatório técnico sintético para revisão de engenharia.", "investigation_performed": ["Contexto do ativo e tendência RMS consultados."], "findings": ["A tendência RMS foi observada na evidência disponível."], "claims": [claim], "evidence_references": evidence_ids, "contradictions": [], "limitations": conclusion["limitations"], "missing_information": [], "suggested_engineer_next_steps": ["Validar em dados operacionais reais antes de qualquer ação."], "escalation_reason": None, "trace_id": state["trace_id"]}
    return {"showcase_type": "deterministic_execution_intelligence", "understanding_source": "test_fixture", "planner_source": "fake_llm", "investigator_source": "fake_llm", "reporter_source": "fake_llm", "external_calls": 0, "canonical_understanding": state["understanding"], "planner_output": plan, "investigation_decisions": [event for event in graph["graph_execution_sequence"] if event["node"] == "investigator_boundary"], "tool_requests": [event["arguments"] for event in state["trace"]["events"] if event["event_type"] == "tool_started"], "trace": state["trace"], "evidence_ledger": state["evidence_ledger"], "investigation_conclusion": conclusion, "reporter_output": report}


def write_showcase(path: Path = EXAMPLE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_showcase(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_showcase())

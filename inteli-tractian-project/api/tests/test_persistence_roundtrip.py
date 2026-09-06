"""Ida e volta da persistência contra o banco real.

Grava uma investigação completa, lê de volta e confere que nada se perdeu no
caminho. Ao final apaga o caso — o teste não deixa resíduo.

Pula quando `SUPABASE_DB_URL` não está no ambiente, para que a suíte continue
verde em máquina sem banco.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.persistence import InvestigationRepository, PersistenceError, is_configured

pytestmark = pytest.mark.skipif(
    not is_configured(), reason="SUPABASE_DB_URL não configurada neste ambiente"
)

NOW = datetime(2026, 9, 6, 12, 42, 3, tzinfo=timezone.utc)


def _payload(case_id: str) -> dict:
    """Uma investigação com conclusão fundamentada e avaliação aprovada."""
    return {
        "case_id": case_id,
        "request_id": f"REQ-{case_id}",
        "trace_id": f"trace-{case_id}",
        "company": "Petro Delta",
        "asset_id": "asset_C710",
        "asset_name": "Compressor C-710",
        "request_message": "O RMS do compressor subiu, mas nenhum insight foi emitido.",
        "request_context": {"tenant_ref": "petro-delta"},
        "request_class": "investigate",
        "phase": "completed",
        "terminal_state": "GROUNDED_COMPLETION",
        "understanding": {"request_class": "investigate", "confidence": 0.92},
        "plan": {"plan_id": "plan-1", "objectives": ["Confirmar o ativo monitorado."]},
        "understanding_source": "llm",
        "planner_source": "llm",
        "reporter_source": "llm",
        "investigation_step_count": 3,
        "tool_call_count": 2,
        "evidence_quality": "HIGH",
        "evidence_quality_reasons": ["2 de 2 afirmações fundamentadas"],
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=8),
        "duration_ms": 8400,
        "trace": [
            {
                "trace_id": f"trace-{case_id}",
                "call_id": "call-context",
                "sequence": 1,
                "event_type": "tool_completed",
                "timestamp": NOW,
                "tool_name": "get_asset_context",
                "client_operation": "get_asset",
                "operation_kind": "read",
                "arguments": {"asset_id": "asset_C710"},
                "details": {"status_code": 200},
                "duration_ms": 420.5,
            },
            {
                "trace_id": f"trace-{case_id}",
                "call_id": "call-rms",
                "sequence": 2,
                "event_type": "tool_completed",
                "timestamp": NOW + timedelta(seconds=1),
                "tool_name": "get_asset_rms",
                "client_operation": "get_asset_rms",
                "operation_kind": "read",
                "arguments": {"asset_id": "asset_C710"},
                "duration_ms": 532.0,
            },
            {
                "trace_id": f"trace-{case_id}",
                "call_id": "call-terminal",
                "sequence": 3,
                "event_type": "terminal_state_reached",
                "timestamp": NOW + timedelta(seconds=8),
            },
        ],
        "evidence": [
            {
                "evidence_id": "E-01",
                "trace_id": f"trace-{case_id}",
                "source_call_id": "call-context",
                "source_trace_sequence": 1,
                "sequence": 1,
                "collected_at": NOW,
                "tool_name": "get_asset_context",
                "client_operation": "get_asset",
                "arguments": {"asset_id": "asset_C710"},
                "evidence_status": "complete",
                "transport_ok": True,
                "status_code": 200,
                "method": "GET",
                "path": "/assets/asset_C710",
                "data": {"online": True},
            },
            {
                "evidence_id": "E-02",
                "trace_id": f"trace-{case_id}",
                "source_call_id": "call-rms",
                "source_trace_sequence": 2,
                "sequence": 2,
                "collected_at": NOW + timedelta(seconds=1),
                "tool_name": "get_asset_rms",
                "client_operation": "get_asset_rms",
                "arguments": {"asset_id": "asset_C710"},
                "evidence_status": "complete",
                "transport_ok": True,
                "status_code": 200,
                "method": "GET",
                "path": "/assets/asset_C710/rms",
            },
        ],
        "conclusion": {
            "conclusion_id": "concl-1",
            "limitations": ["A API não expõe o limiar interno do modelo."],
            "unresolved_points": [],
            "reason_codes": ["EVIDENCE_SUFFICIENT"],
        },
        "claims": [
            {
                "claim_id": "CL-01",
                "statement": "O compressor está online e corresponde ao ativo solicitado.",
                "status": "supported",
                "supporting_evidence_ids": ["E-01"],
                "contradictory_evidence_ids": [],
            },
            {
                "claim_id": "CL-02",
                "statement": "O RMS subiu de 2,8 para 4,2 mm/s.",
                "status": "qualified",
                "limitation": "Janela limitada ao que a API expõe.",
                "supporting_evidence_ids": ["E-02"],
                "contradictory_evidence_ids": [],
            },
        ],
        "report": {
            "report_id": "RPT-01",
            "executive_summary": "O ativo está online e o RMS exposto está subindo.",
            "investigation_performed": ["Validou o contexto do ativo."],
            "findings": ["O RMS recente subiu."],
            "evidence_references": ["E-01", "E-02"],
            "limitations": ["Sem acesso ao limiar do modelo."],
            "suggested_engineer_next_steps": ["Revisar a telemetria de insights."],
        },
        "evaluation": {
            "decision": {
                "evaluation_id": f"eval-{case_id}",
                "run_id": f"run-{case_id}",
                "final_verdict": "APPROVED",
                "approved": True,
                "human_review_required": False,
                "recommended_action": "PROCEED",
                "overall_score": 3.85,
                "overall_score_max": 4,
                "agreement_level": "HIGH",
                "hard_failures": [],
                "arbitration_used": False,
                "judge_a_verdict": "PASS",
                "judge_b_verdict": "PASS",
                "barema_version": "barema-v1",
                "headline": "Aprovado, com 3,9 de 4.",
                "evaluated_at": NOW + timedelta(seconds=10),
                "critical_score_summary": [
                    {"criterion": "SAFETY", "score": 4, "meets_minimum": True},
                    {"criterion": "EVIDENCE_GROUNDING", "score": 4, "meets_minimum": True},
                ],
                "warnings": [
                    {
                        "code": "DATA_LIMITATION",
                        "detail": "Janela de RMS mais estreita do que a pedida.",
                        "criterion": "EVIDENCE_GROUNDING",
                    }
                ],
                "review_reasons": [],
            },
            "judge_a": {
                "judge_id": "judge_a",
                "verdict": "PASS",
                "overall_score": 3.9,
                "confidence_in_evaluation": "HIGH",
                "needs_human_review": False,
                "strengths": ["Toda afirmação é rastreável."],
                "weaknesses": [],
                "evidence_references": ["E-01"],
                "provider": "gemini",
                "model": "gemini-3.5-flash-lite",
                "criteria_scores": [
                    {"criterion": "SAFETY", "score": 4, "reason": "Nenhuma ação executada."},
                    {
                        "criterion": "EVIDENCE_GROUNDING",
                        "score": 4,
                        "reason": "Lineage íntegra.",
                        "evidence_references": ["E-01", "E-02"],
                    },
                ],
            },
            "judge_b": {
                "judge_id": "judge_b",
                "verdict": "PASS",
                "overall_score": 3.8,
                "confidence_in_evaluation": "HIGH",
                "needs_human_review": False,
                "strengths": ["Limitação declarada no relatório."],
                "weaknesses": ["O resumo poderia nomear o ponto de medição."],
                "criteria_scores": [
                    {"criterion": "SAFETY", "score": 4, "reason": "Somente leitura."},
                    {"criterion": "REPORT_QUALITY", "score": 3, "reason": "Bom, com ressalva."},
                ],
            },
            "agreement": {
                "agreement_level": "HIGH",
                "verdict_match": True,
                "hard_failure_match": True,
                "mean_absolute_delta": 0.2,
                "max_delta": 1,
                "arbitration_required": False,
                "rationale": "Mesmo veredito, diferença de um nível.",
                "disagreements": [
                    {
                        "criterion": "REPORT_QUALITY",
                        "judge_a_score": 4,
                        "judge_b_score": 3,
                        "delta": 1,
                    }
                ],
            },
        },
    }


@pytest.fixture
def repo() -> InvestigationRepository:
    return InvestigationRepository()


@pytest.fixture
def case_id() -> str:
    return f"TEST-{uuid.uuid4().hex[:10].upper()}"


@pytest.fixture(autouse=True)
def cleanup(repo: InvestigationRepository, case_id: str):
    yield
    with repo.connection() as conn, conn.transaction():
        conn.execute("delete from investigation.investigation_run where case_id = %s", (case_id,))


def test_saves_and_reads_back_the_whole_investigation(repo, case_id):
    saved = repo.save_investigation(_payload(case_id))
    assert saved.case_id == case_id

    dossier = repo.get_investigation(case_id)
    assert dossier is not None
    assert dossier["terminal_state"] == "GROUNDED_COMPLETION"
    assert dossier["asset_name"] == "Compressor C-710"
    assert len(dossier["trace"]) == 3
    assert len(dossier["evidence"]) == 2

    # A proveniência sobrevive à ida e volta.
    claims = {c["claim_id"]: c for c in dossier["claims"]}
    assert claims["CL-01"]["supporting_evidence_ids"] == ["E-01"]
    assert claims["CL-02"]["status"] == "qualified"
    assert claims["CL-02"]["limitation"]

    assert dossier["report"]["report_id"] == "RPT-01"
    assert dossier["human_handoff"] is None

    evaluation = dossier["evaluation"]
    assert evaluation["decision"]["final_verdict"] == "APPROVED"
    assert float(evaluation["decision"]["overall_score"]) == pytest.approx(3.85)
    assert len(evaluation["decision"]["critical_score_summary"]) == 2
    assert len(evaluation["decision"]["warnings"]) == 1
    assert evaluation["decision"]["review_reasons"] == []
    assert evaluation["judge_a"]["verdict"] == "PASS"
    assert len(evaluation["judge_b"]["criteria_scores"]) == 2
    assert evaluation["agreement"]["disagreements"][0]["delta"] == 1
    assert "arbitration" not in evaluation


def test_regravar_o_mesmo_caso_substitui_em_vez_de_duplicar(repo, case_id):
    repo.save_investigation(_payload(case_id))
    repo.save_investigation(_payload(case_id))

    dossier = repo.get_investigation(case_id)
    assert len(dossier["trace"]) == 3
    assert len(dossier["evidence"]) == 2
    assert len(dossier["claims"]) == 2


def test_evidencia_citada_que_nao_existe_e_recusada(repo, case_id):
    """A hard failure EVIDENCE_REFERENCE_NOT_FOUND não chega a virar linha."""
    payload = _payload(case_id)
    payload["claims"][0]["supporting_evidence_ids"] = ["E-99"]

    with pytest.raises(PersistenceError, match="E-99"):
        repo.save_investigation(payload)

    # A transação inteira voltou atrás: nem a execução ficou.
    assert repo.get_investigation(case_id) is None


def test_evidencia_sem_evento_de_trajetoria_e_recusada(repo, case_id):
    """BROKEN_EVIDENCE_LINEAGE barrada pela chave estrangeira composta."""
    payload = _payload(case_id)
    payload["evidence"][0]["source_trace_sequence"] = 99

    with pytest.raises(PersistenceError):
        repo.save_investigation(payload)
    assert repo.get_investigation(case_id) is None


def test_aprovar_com_condicao_critica_e_recusado(repo, case_id):
    payload = _payload(case_id)
    payload["evaluation"]["decision"]["hard_failures"] = ["REPORTER_FABRICATED_CLAIM"]

    with pytest.raises(PersistenceError):
        repo.save_investigation(payload)
    assert repo.get_investigation(case_id) is None


def test_fila_de_revisao_traz_o_caso_encaminhado(repo, case_id):
    payload = _payload(case_id)
    payload["terminal_state"] = "SAFE_ESCALATION"
    payload["human_handoff"] = {
        "handoff_id": "HO-01",
        "reason_codes": ["CONFLICTING_DIAGNOSES"],
        "evidence_ids": ["E-01"],
        "missing_information": ["Espectro validado"],
        "suggested_next_step": "Comparar o espectro com a inspeção.",
    }
    repo.save_investigation(payload)

    queue = {row["case_id"] for row in repo.review_queue()}
    assert case_id in queue


def test_listagem_traz_o_veredicto_junto(repo, case_id):
    repo.save_investigation(_payload(case_id))
    rows = {row["case_id"]: row for row in repo.list_investigations(limit=100)}
    assert case_id in rows
    assert rows[case_id]["final_verdict"] == "APPROVED"
    assert rows[case_id]["evidence_count"] == 2

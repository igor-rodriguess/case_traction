"""Integração do console: API, persistência progressiva e serviço de aplicação.

Os testes que tocam banco pulam quando `SUPABASE_DB_URL` não está no ambiente.
Nenhum deles depende de provedor de LLM: o pipeline é injetado por fake, porque
o que se verifica aqui é a coordenação, não a inteligência.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.application.investigation_service import _evidence_quality, _quality_reasons
from app.main import app
from app.persistence import ProgressiveWriter, RunIdentity, is_configured

client = TestClient(app)

needs_db = pytest.mark.skipif(
    not is_configured(), reason="SUPABASE_DB_URL não configurada neste ambiente"
)


# ---------------------------------------------------------------------------
# Contrato da API
# ---------------------------------------------------------------------------


def test_health_reporta_api_e_banco_sem_credencial():
    body = client.get("/api/v1/health").json()
    assert body["api"] == "healthy"
    assert body["database"] in {"connected", "unavailable", "not_configured"}
    # Nenhum segredo pode atravessar a fronteira da API.
    serialized = str(body).lower()
    for forbidden in ("password", "postgresql://", "service_role", "secret", "api_key"):
        assert forbidden not in serialized


def test_investigacao_inexistente_devolve_erro_tipado():
    response = client.get("/api/v1/investigations/CASE-INEXISTENTE")
    assert response.status_code == 404
    body = response.json()
    detail = body.get("detail") or body["message"]
    assert detail["code"] == "NOT_FOUND"
    assert "não encontrada" in detail["message"]
    # Sem stack trace vazando para o cliente.
    assert "Traceback" not in str(detail)


def test_criacao_valida_a_mensagem_antes_de_tocar_no_banco():
    response = client.post("/api/v1/investigations", json={"message": "curto"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Qualidade derivada
# ---------------------------------------------------------------------------


def test_qualidade_sem_evidencia_e_insuficiente():
    assert _evidence_quality([], None) == "INSUFFICIENT_EVIDENCE"
    assert _quality_reasons([], None) == ["Nenhuma evidência foi coletada"]


def test_qualidade_alta_exige_conclusao_e_zero_degradadas():
    evidence = [{"evidence_status": "complete"}, {"evidence_status": "complete"}]
    assert _evidence_quality(evidence, {"claims": [{}]}) == "HIGH"
    # A mesma evidência sem conclusão não é alta: não houve o que fundamentar.
    assert _evidence_quality(evidence, None) == "MEDIUM"


def test_qualidade_cai_quando_a_maioria_esta_degradada():
    evidence = [
        {"evidence_status": "complete"},
        {"evidence_status": "inconclusive"},
        {"evidence_status": "unavailable"},
    ]
    assert _evidence_quality(evidence, None) == "LOW"


# ---------------------------------------------------------------------------
# Persistência progressiva
# ---------------------------------------------------------------------------


@needs_db
def test_persistencia_progressiva_preserva_o_que_ja_era_verdade():
    """§4: uma falha tardia não pode apagar a trajetória já vivida."""
    case_id = f"TEST-PROG-{uuid.uuid4().hex[:8].upper()}"
    writer = ProgressiveWriter()
    writer.open_run(
        RunIdentity(
            case_id=case_id,
            request_id=f"req-{case_id}",
            trace_id=f"trace-{case_id}",
            request_message="mensagem de teste",
        )
    )

    base = {
        "case_id": case_id,
        "request_id": f"req-{case_id}",
        "trace_id": f"trace-{case_id}",
        "request_message": "mensagem de teste",
        "phase": "understanding",
    }

    try:
        # Primeiro commit: entendimento.
        writer.sync({**base, "understanding": {"request_class": "investigate"}})

        # Segundo commit: uma consulta e a evidência que ela produziu.
        writer.sync(
            {
                **base,
                "trace": [
                    {
                        "trace_id": f"trace-{case_id}",
                        "call_id": "call-1",
                        "sequence": 1,
                        "event_type": "tool_completed",
                        "timestamp": "2026-09-06T12:00:00Z",
                        "tool_name": "get_asset_context",
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "E-01",
                        "trace_id": f"trace-{case_id}",
                        "source_call_id": "call-1",
                        "source_trace_sequence": 1,
                        "sequence": 1,
                        "collected_at": "2026-09-06T12:00:00Z",
                        "tool_name": "get_asset_context",
                        "client_operation": "get_asset",
                        "evidence_status": "complete",
                        "transport_ok": True,
                        "status_code": 200,
                        "method": "GET",
                        "path": "/assets/x",
                    }
                ],
            }
        )

        # Terceiro: a execução falha. O que já foi gravado continua lá.
        writer.finish(terminal_state="FAILED", duration_ms=1200)

        from app.persistence import InvestigationRepository

        dossier = InvestigationRepository().get_investigation(case_id)
        assert dossier is not None
        assert dossier["terminal_state"] == "FAILED"
        assert dossier["understanding"] == {"request_class": "investigate"}
        assert len(dossier["trace"]) == 1
        assert len(dossier["evidence"]) == 1
    finally:
        from app.persistence import InvestigationRepository

        with InvestigationRepository().connection() as conn, conn.transaction():
            conn.execute(
                "delete from investigation.investigation_run where case_id = %s", (case_id,)
            )


@needs_db
def test_sync_repetido_nao_duplica_trajetoria():
    """Idempotência por `(run_id, sequence)`: o polling pode reenviar à vontade."""
    case_id = f"TEST-IDEM-{uuid.uuid4().hex[:8].upper()}"
    writer = ProgressiveWriter()
    writer.open_run(
        RunIdentity(
            case_id=case_id,
            request_id=f"req-{case_id}",
            trace_id=f"trace-{case_id}",
            request_message="mensagem",
        )
    )
    snapshot = {
        "case_id": case_id,
        "request_id": f"req-{case_id}",
        "trace_id": f"trace-{case_id}",
        "request_message": "mensagem",
        "trace": [
            {
                "trace_id": f"trace-{case_id}",
                "call_id": "call-1",
                "sequence": 1,
                "event_type": "understanding_completed",
                "timestamp": "2026-09-06T12:00:00Z",
            }
        ],
    }
    try:
        writer.sync(snapshot)
        writer.sync(snapshot)
        writer.sync(snapshot)

        from app.persistence import InvestigationRepository

        dossier = InvestigationRepository().get_investigation(case_id)
        assert len(dossier["trace"]) == 1
    finally:
        from app.persistence import InvestigationRepository

        with InvestigationRepository().connection() as conn, conn.transaction():
            conn.execute(
                "delete from investigation.investigation_run where case_id = %s", (case_id,)
            )


@needs_db
def test_listagem_e_dossie_respondem_pelo_endpoint():
    case_id = f"TEST-API-{uuid.uuid4().hex[:8].upper()}"
    writer = ProgressiveWriter()
    writer.open_run(
        RunIdentity(
            case_id=case_id,
            request_id=f"req-{case_id}",
            trace_id=f"trace-{case_id}",
            request_message="mensagem de teste da API",
        )
    )
    try:
        listed = client.get("/api/v1/investigations?limit=200").json()
        assert any(row["case_id"] == case_id for row in listed)

        dossier = client.get(f"/api/v1/investigations/{case_id}").json()
        assert dossier["case_id"] == case_id
        assert dossier["trace"] == []
        assert dossier["evaluation"] is None

        # Avaliação ausente é 404 com motivo, não 500.
        response = client.get(f"/api/v1/investigations/{case_id}/evaluation")
        assert response.status_code == 404
        body = response.json()
        assert (body.get("detail") or body["message"])["code"] == "NOT_FOUND"
    finally:
        from app.persistence import InvestigationRepository

        with InvestigationRepository().connection() as conn, conn.transaction():
            conn.execute(
                "delete from investigation.investigation_run where case_id = %s", (case_id,)
            )

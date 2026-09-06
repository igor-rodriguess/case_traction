"""API do console de investigação.

Vive sob `/api/v1` no mesmo processo da API industrial simulada, que ocupa a
raiz (`/assets`, `/analyses`, …). Não há colisão de caminho e não há um segundo
servidor para orquestrar: as READ tools continuam consultando a API industrial
exatamente como antes.

Fronteira clara: **o frontend fala com esta API, nunca com o Supabase**. A
credencial de banco não sai daqui, e nenhuma resposta carrega segredo.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from app.application import CreatedInvestigation, InvestigationService, NewInvestigation
from app.persistence import (
    InvestigationRepository,
    MissingConfiguration,
    PersistenceError,
    is_configured,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Console de investigação"])

# Execuções em andamento neste processo. Serve para o health e para não
# reprocessar o mesmo caso; não é registro durável — o banco é.
_running: set[str] = set()
_running_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Contrato de erro
# ---------------------------------------------------------------------------

ErrorCode = Literal[
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "PIPELINE_ERROR",
    "PERSISTENCE_ERROR",
    "PROVIDER_ERROR",
    "TOOL_ERROR",
    "NOT_CONFIGURED",
]


class ApiError(BaseModel):
    """Erro sem stack trace. O detalhe técnico fica no log do servidor."""

    code: ErrorCode
    message: str
    detail: str | None = None


def _fail(http_status: int, code: ErrorCode, message: str, detail: str | None = None):
    raise HTTPException(
        status_code=http_status,
        detail=ApiError(code=code, message=message, detail=detail).model_dump(),
    )


def _repository() -> InvestigationRepository:
    if not is_configured():
        _fail(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "NOT_CONFIGURED",
            "O serviço de investigação está sem banco configurado.",
            "Defina SUPABASE_DB_URL no ambiente da API.",
        )
    try:
        return InvestigationRepository()
    except MissingConfiguration as exc:
        _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "NOT_CONFIGURED", str(exc))


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


class NewInvestigationRequest(BaseModel):
    message: str = Field(min_length=8, max_length=4000, description="Dúvida técnica do solicitante")
    tenant_ref: str | None = Field(default=None, max_length=120)
    asset_refs: tuple[str, ...] = ()
    role: str | None = Field(default=None, max_length=80)


class AcceptedInvestigation(BaseModel):
    investigation_id: str
    case_id: str
    phase: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Execução em segundo plano
# ---------------------------------------------------------------------------


def _execute(created: CreatedInvestigation, request: NewInvestigation) -> None:
    """Roda o pipeline fora do ciclo da requisição.

    Execução in-process: adequada para demonstração e instância única. Se o
    processo reiniciar no meio, o que já foi persistido permanece — o caso fica
    sem estado terminal, e isso é visível.
    """
    with _running_lock:
        _running.add(created.case_id)
    try:
        InvestigationService().execute(created, request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("investigação %s falhou: %s", created.case_id, exc)
    finally:
        with _running_lock:
            _running.discard(created.case_id)


@router.post(
    "/investigations",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedInvestigation,
    summary="Cria uma investigação e inicia a execução",
)
def create_investigation(
    payload: NewInvestigationRequest, background: BackgroundTasks
) -> AcceptedInvestigation:
    """Devolve o identificador imediatamente; o pipeline segue em segundo plano."""
    if not is_configured():
        _fail(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "NOT_CONFIGURED",
            "O serviço de investigação está sem banco configurado.",
        )

    request = NewInvestigation(
        message=payload.message,
        tenant_ref=payload.tenant_ref,
        asset_refs=tuple(payload.asset_refs),
        role=payload.role,
    )
    try:
        created = InvestigationService().create(request)
    except PersistenceError as exc:
        logger.error("não foi possível criar a investigação: %s", exc)
        _fail(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PERSISTENCE_ERROR",
            "Não foi possível registrar a investigação.",
        )

    background.add_task(_execute, created, request)

    return AcceptedInvestigation(
        investigation_id=created.case_id,
        case_id=created.case_id,
        phase=created.phase,
        created_at=created.created_at,
    )


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


@router.get("/investigations", summary="Lista investigações")
def list_investigations(limit: int = 50) -> list[dict[str, Any]]:
    repo = _repository()
    try:
        rows = repo.list_investigations(limit=min(max(limit, 1), 200))
    except PersistenceError as exc:
        logger.error("falha ao listar: %s", exc)
        _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "PERSISTENCE_ERROR", "Banco indisponível.")
    for row in rows:
        row["running"] = row["case_id"] in _running
    return rows


@router.get("/investigations/{case_id}", summary="Dossiê consolidado")
def get_investigation(case_id: str) -> dict[str, Any]:
    """DTO único: o frontend não precisa entender o schema do banco."""
    repo = _repository()
    try:
        dossier = repo.get_investigation(case_id)
    except PersistenceError as exc:
        logger.error("falha ao ler %s: %s", case_id, exc)
        _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "PERSISTENCE_ERROR", "Banco indisponível.")
    if dossier is None:
        _fail(status.HTTP_404_NOT_FOUND, "NOT_FOUND", f"Investigação {case_id} não encontrada.")
    dossier["running"] = case_id in _running
    return dossier


@router.get("/investigations/{case_id}/trace", summary="Trajetória ordenada")
def get_trace(case_id: str) -> list[dict[str, Any]]:
    dossier = get_investigation(case_id)
    return dossier["trace"]


@router.get("/investigations/{case_id}/evidence", summary="Evidências da execução")
def get_evidence(case_id: str) -> list[dict[str, Any]]:
    dossier = get_investigation(case_id)
    return dossier["evidence"]


@router.get("/investigations/{case_id}/evaluation", summary="Avaliação e avaliadores")
def get_evaluation(case_id: str) -> dict[str, Any]:
    dossier = get_investigation(case_id)
    evaluation = dossier.get("evaluation")
    if evaluation is None:
        _fail(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "Esta investigação ainda não foi avaliada.",
            f"Estado terminal: {dossier.get('terminal_state') or 'em execução'}.",
        )
    return evaluation


@router.get("/investigations/{case_id}/human-review", summary="Encaminhamento humano")
def get_human_review(case_id: str) -> dict[str, Any]:
    dossier = get_investigation(case_id)
    handoff = dossier.get("human_handoff")
    evaluation = dossier.get("evaluation")
    required = bool(handoff) or bool(
        evaluation and evaluation["decision"].get("human_review_required")
    )
    if not required:
        _fail(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "Esta investigação não exige revisão técnica.",
        )
    return {
        "case_id": case_id,
        "handoff": handoff,
        "decision": (evaluation or {}).get("decision"),
        "unresolved": dossier.get("unresolved_points") or [],
    }


@router.get("/review-queue", summary="Fila de revisão técnica")
def review_queue() -> list[dict[str, Any]]:
    repo = _repository()
    try:
        return repo.review_queue()
    except PersistenceError as exc:
        logger.error("falha na fila: %s", exc)
        _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "PERSISTENCE_ERROR", "Banco indisponível.")


@router.get("/health", summary="Saúde do serviço")
def health() -> dict[str, Any]:
    """Sem credenciais. Só o que um operador precisa saber."""
    database = "not_configured"
    if is_configured():
        try:
            with InvestigationRepository().connection() as conn:
                conn.execute("select 1")
            database = "connected"
        except Exception:  # noqa: BLE001
            database = "unavailable"
    with _running_lock:
        running = len(_running)
    return {
        "api": "healthy",
        "database": database,
        "running_investigations": running,
        "checked_at": datetime.now(timezone.utc),
    }

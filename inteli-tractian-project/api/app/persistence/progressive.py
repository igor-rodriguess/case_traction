"""Persistência progressiva da investigação.

A gravação em bloco único (`InvestigationRepository.save_investigation`) protege
integridade, mas torna a execução invisível até o fim — o frontend não consegue
acompanhar, e uma falha tardia apagaria toda a trajetória já vivida.

Aqui a atomicidade muda de granularidade sem afrouxar nada: cada chamada de
`sync` é **uma transação**, e cada transação fecha uma unidade que faz sentido
sozinha.

    entendimento concluído  → run + eventos de trajetória          commit
    plano criado            → run + eventos                        commit
    consulta executada      → evento + evidências que ela gerou    commit
    conclusão produzida     → conclusão + afirmações + vínculos     commit
    relatório gerado        → relatório                            commit
    avaliação concluída     → decisão + avaliadores + divergências  commit

A evidência continua nascendo no mesmo commit do evento que a originou, então a
chave estrangeira composta que garante a proveniência nunca fica pendurada. Uma
falha no passo seguinte não desfaz o que já era verdade.

A escrita é idempotente por `(run_id, sequence)`: chamar `sync` de novo com o
mesmo estado não duplica nada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row

from .repository import SCHEMA, PersistenceError, _enum, _json, _list, _readable
from .settings import DatabaseSettings, database_settings


@dataclass(frozen=True)
class RunIdentity:
    """Identidade do caso na origem, antes de existir linha no banco."""

    case_id: str
    request_id: str
    trace_id: str
    request_message: str
    company: str | None = None
    asset_id: str | None = None
    asset_name: str | None = None
    request_context: Mapping[str, Any] | None = None


class ProgressiveWriter:
    """Grava o andamento de uma investigação, uma unidade consistente por vez."""

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        self._settings = settings or database_settings()
        self._run_id: str | None = None

    # ------------------------------------------------------------------
    # Conexão
    # ------------------------------------------------------------------

    def _connect(self) -> psycopg.Connection:
        try:
            return psycopg.connect(
                self._settings.url,
                connect_timeout=self._settings.connect_timeout,
                application_name=self._settings.application_name,
                row_factory=dict_row,
            )
        except psycopg.Error as exc:
            raise PersistenceError(
                f"não foi possível conectar ao banco: {exc.__class__.__name__}"
            ) from None

    @property
    def run_id(self) -> str | None:
        return self._run_id

    # ------------------------------------------------------------------
    # Abertura
    # ------------------------------------------------------------------

    def open_run(self, identity: RunIdentity) -> str:
        """Cria a execução em `received`. Primeira transação, e a mais curta.

        Depois dela o caso já existe para o frontend, mesmo que o pipeline ainda
        não tenha dado o primeiro passo.
        """
        with self._connect() as conn:
            try:
                with conn.transaction():
                    row = conn.execute(
                        f"""
                        insert into {SCHEMA}.investigation_run
                            (case_id, request_id, trace_id, request_message, request_context,
                             company, asset_id, asset_name, phase, started_at)
                        values (%s, %s, %s, %s, %s, %s, %s, %s, 'received', now())
                        on conflict (case_id) do update set
                            request_message = excluded.request_message,
                            request_context = excluded.request_context
                        returning id
                        """,
                        (
                            identity.case_id,
                            identity.request_id,
                            identity.trace_id,
                            identity.request_message,
                            _json(dict(identity.request_context or {})),
                            identity.company,
                            identity.asset_id,
                            identity.asset_name,
                        ),
                    ).fetchone()
            except psycopg.Error as exc:
                raise PersistenceError(_readable(exc)) from None
        self._run_id = str(row["id"])
        return self._run_id

    # ------------------------------------------------------------------
    # Sincronização incremental
    # ------------------------------------------------------------------

    def sync(self, snapshot: Mapping[str, Any]) -> None:
        """Grava o que ainda não está no banco. Uma transação, sempre.

        `snapshot` é o estado serializado da investigação no momento — a mesma
        forma que `save_investigation` consome.
        """
        if self._run_id is None:
            raise PersistenceError("sync chamado antes de open_run")

        with self._connect() as conn:
            try:
                with conn.transaction():
                    self._update_run(conn, snapshot)
                    self._append_trace(conn, snapshot.get("trace") or ())
                    self._append_evidence(conn, snapshot.get("evidence") or ())
                    self._write_conclusion(conn, snapshot)
                    self._write_report(conn, snapshot.get("report"))
                    self._write_handoff(conn, snapshot.get("human_handoff"))
            except psycopg.Error as exc:
                raise PersistenceError(_readable(exc)) from None

    def _update_run(self, conn: psycopg.Connection, snapshot: Mapping[str, Any]) -> None:
        conn.execute(
            f"""
            update {SCHEMA}.investigation_run set
                request_class = coalesce(%(request_class)s, request_class),
                phase = coalesce(%(phase)s, phase),
                terminal_state = coalesce(%(terminal_state)s, terminal_state),
                understanding = coalesce(%(understanding)s, understanding),
                plan = coalesce(%(plan)s, plan),
                understanding_source = coalesce(%(understanding_source)s, understanding_source),
                planner_source = coalesce(%(planner_source)s, planner_source),
                reporter_source = coalesce(%(reporter_source)s, reporter_source),
                asset_id = coalesce(%(asset_id)s, asset_id),
                asset_name = coalesce(%(asset_name)s, asset_name),
                investigation_step_count = coalesce(%(steps)s, investigation_step_count),
                tool_call_count = coalesce(%(calls)s, tool_call_count),
                evidence_quality = coalesce(%(evidence_quality)s, evidence_quality),
                evidence_quality_reasons = case
                    when %(quality_reasons)s::text[] is null or cardinality(%(quality_reasons)s::text[]) = 0
                    then evidence_quality_reasons else %(quality_reasons)s::text[] end,
                error_code = coalesce(%(error_code)s, error_code),
                error_summary = coalesce(%(error_summary)s, error_summary),
                error_can_continue = coalesce(%(error_can_continue)s, error_can_continue),
                finished_at = coalesce(%(finished_at)s, finished_at),
                duration_ms = coalesce(%(duration_ms)s, duration_ms)
            where id = %(run_id)s
            """,
            {
                "run_id": self._run_id,
                "request_class": snapshot.get("request_class"),
                "phase": snapshot.get("phase"),
                "terminal_state": snapshot.get("terminal_state"),
                "understanding": _json(snapshot.get("understanding")),
                "plan": _json(snapshot.get("plan")),
                "understanding_source": snapshot.get("understanding_source"),
                "planner_source": snapshot.get("planner_source"),
                "reporter_source": snapshot.get("reporter_source"),
                "asset_id": snapshot.get("asset_id"),
                "asset_name": snapshot.get("asset_name"),
                "steps": snapshot.get("investigation_step_count"),
                "calls": snapshot.get("tool_call_count"),
                "evidence_quality": snapshot.get("evidence_quality"),
                "quality_reasons": _list(snapshot.get("evidence_quality_reasons")),
                "error_code": snapshot.get("error_code"),
                "error_summary": snapshot.get("error_summary"),
                "error_can_continue": snapshot.get("error_can_continue"),
                "finished_at": snapshot.get("finished_at"),
                "duration_ms": snapshot.get("duration_ms"),
            },
        )

    def _persisted_max(self, conn: psycopg.Connection, table: str) -> int:
        row = conn.execute(
            f"select coalesce(max(sequence), 0) as m from {SCHEMA}.{table} where run_id = %s",
            (self._run_id,),
        ).fetchone()
        return int(row["m"])

    def _append_trace(
        self, conn: psycopg.Connection, events: Sequence[Mapping[str, Any]]
    ) -> None:
        highest = self._persisted_max(conn, "trace_event")
        for event in events:
            if int(event["sequence"]) <= highest:
                continue
            conn.execute(
                f"""
                insert into {SCHEMA}.trace_event (
                    run_id, trace_id, call_id, sequence, event_type, occurred_at,
                    tool_name, category, operation_kind, client_operation,
                    arguments, details, duration_ms, result, failure
                ) values (
                    %(run_id)s, %(trace_id)s, %(call_id)s, %(sequence)s, %(event_type)s,
                    %(occurred_at)s, %(tool_name)s, %(category)s, %(operation_kind)s,
                    %(client_operation)s, %(arguments)s, %(details)s, %(duration_ms)s,
                    %(result)s, %(failure)s
                )
                on conflict (run_id, sequence) do nothing
                """,
                {
                    "run_id": self._run_id,
                    "trace_id": event["trace_id"],
                    "call_id": event["call_id"],
                    "sequence": event["sequence"],
                    "event_type": _enum(event["event_type"]),
                    "occurred_at": event.get("timestamp") or event.get("occurred_at"),
                    "tool_name": event.get("tool_name"),
                    "category": event.get("category"),
                    "operation_kind": _enum(event.get("operation_kind")),
                    "client_operation": event.get("client_operation"),
                    "arguments": _json(event.get("arguments") or {}),
                    "details": _json(event.get("details") or {}),
                    "duration_ms": event.get("duration_ms"),
                    "result": _json(event.get("result")),
                    "failure": _json(event.get("failure")),
                },
            )

    def _append_evidence(
        self, conn: psycopg.Connection, records: Sequence[Mapping[str, Any]]
    ) -> None:
        highest = self._persisted_max(conn, "evidence_record")
        for record in records:
            if int(record["sequence"]) <= highest:
                continue
            conn.execute(
                f"""
                insert into {SCHEMA}.evidence_record (
                    run_id, evidence_id, trace_id, source_call_id, source_trace_sequence,
                    sequence, collected_at, tool_name, client_operation, arguments,
                    evidence_status, transport_ok, status_code, method, path, data, notes
                ) values (
                    %(run_id)s, %(evidence_id)s, %(trace_id)s, %(source_call_id)s,
                    %(source_trace_sequence)s, %(sequence)s, %(collected_at)s, %(tool_name)s,
                    %(client_operation)s, %(arguments)s, %(evidence_status)s, %(transport_ok)s,
                    %(status_code)s, %(method)s, %(path)s, %(data)s, %(notes)s
                )
                on conflict (run_id, evidence_id) do nothing
                """,
                {
                    "run_id": self._run_id,
                    "evidence_id": record["evidence_id"],
                    "trace_id": record["trace_id"],
                    "source_call_id": record["source_call_id"],
                    "source_trace_sequence": record["source_trace_sequence"],
                    "sequence": record["sequence"],
                    "collected_at": record["collected_at"],
                    "tool_name": record["tool_name"],
                    "client_operation": record["client_operation"],
                    "arguments": _json(record.get("arguments") or {}),
                    "evidence_status": _enum(record["evidence_status"]),
                    "transport_ok": record["transport_ok"],
                    "status_code": record.get("status_code"),
                    "method": record["method"],
                    "path": record["path"],
                    "data": _json(record.get("data")),
                    "notes": record.get("notes"),
                },
            )

    def _write_conclusion(self, conn: psycopg.Connection, snapshot: Mapping[str, Any]) -> None:
        conclusion = snapshot.get("conclusion")
        if not conclusion:
            return
        existing = conn.execute(
            f"select id from {SCHEMA}.conclusion where run_id = %s", (self._run_id,)
        ).fetchone()
        if existing:
            return

        row = conn.execute(
            f"""
            insert into {SCHEMA}.conclusion
                (run_id, conclusion_id, limitations, unresolved_points, reason_codes)
            values (%s, %s, %s, %s, %s)
            returning id
            """,
            (
                self._run_id,
                conclusion.get("conclusion_id") or f"conclusion_{snapshot['case_id']}",
                _list(conclusion.get("limitations")),
                _list(conclusion.get("unresolved_points")),
                _list(conclusion.get("reason_codes")),
            ),
        ).fetchone()

        evidence_pk = {
            r["evidence_id"]: r["id"]
            for r in conn.execute(
                f"select id, evidence_id from {SCHEMA}.evidence_record where run_id = %s",
                (self._run_id,),
            ).fetchall()
        }

        for claim in conclusion.get("claims") or ():
            claim_row = conn.execute(
                f"""
                insert into {SCHEMA}.claim
                    (run_id, conclusion_pk, claim_id, statement, status, limitation)
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    self._run_id,
                    row["id"],
                    claim["claim_id"],
                    claim["statement"],
                    _enum(claim.get("status") or "supported"),
                    claim.get("limitation"),
                ),
            ).fetchone()

            pairs = (
                (claim.get("supporting_evidence_ids") or (), "supporting"),
                (claim.get("contradictory_evidence_ids") or (), "contradictory"),
            )
            for evidence_ids, relation in pairs:
                for evidence_id in evidence_ids:
                    target = evidence_pk.get(str(evidence_id))
                    if target is None:
                        # EVIDENCE_REFERENCE_NOT_FOUND: a transação inteira volta.
                        raise PersistenceError(
                            f"afirmação {claim['claim_id']} cita a evidência {evidence_id}, "
                            "ausente do registro desta investigação"
                        )
                    conn.execute(
                        f"insert into {SCHEMA}.claim_evidence (claim_pk, evidence_pk, relation) "
                        "values (%s, %s, %s) on conflict do nothing",
                        (claim_row["id"], target, relation),
                    )

    def _write_report(
        self, conn: psycopg.Connection, report: Mapping[str, Any] | None
    ) -> None:
        if not report:
            return
        conn.execute(
            f"""
            insert into {SCHEMA}.technical_report (
                run_id, report_id, audience, executive_summary, investigation_performed,
                findings, evidence_references, contradictions, limitations,
                missing_information, suggested_engineer_next_steps, escalation_reason
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id) do nothing
            """,
            (
                self._run_id,
                report["report_id"],
                report.get("audience", "tractian_engineering_team"),
                report["executive_summary"],
                _list(report.get("investigation_performed")),
                _list(report.get("findings")),
                _list(report.get("evidence_references")),
                _list(report.get("contradictions")),
                _list(report.get("limitations")),
                _list(report.get("missing_information")),
                _list(report.get("suggested_engineer_next_steps")),
                report.get("escalation_reason"),
            ),
        )

    def _write_handoff(
        self, conn: psycopg.Connection, handoff: Mapping[str, Any] | None
    ) -> None:
        if not handoff:
            return
        conn.execute(
            f"""
            insert into {SCHEMA}.human_handoff
                (run_id, handoff_id, reason_codes, evidence_ids, missing_information,
                 suggested_next_step)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (run_id) do nothing
            """,
            (
                self._run_id,
                handoff["handoff_id"],
                _list(handoff.get("reason_codes")) or ["HUMAN_REVIEW_REQUIRED"],
                _list(handoff.get("evidence_ids")),
                _list(handoff.get("missing_information")),
                handoff.get("suggested_next_step"),
            ),
        )

    # ------------------------------------------------------------------
    # Avaliação
    # ------------------------------------------------------------------

    def record_evaluation(self, evaluation: Mapping[str, Any]) -> None:
        """Decisão final, avaliadores, notas, concordância e arbitragem: um commit."""
        if self._run_id is None:
            raise PersistenceError("record_evaluation chamado antes de open_run")

        from .repository import InvestigationRepository

        repo = InvestigationRepository(self._settings)
        with self._connect() as conn:
            try:
                with conn.transaction():
                    conn.execute(
                        f"delete from {SCHEMA}.evaluation where run_id = %s", (self._run_id,)
                    )
                    repo._insert_evaluation(conn, self._run_id, evaluation)
            except psycopg.Error as exc:
                raise PersistenceError(_readable(exc)) from None

    def finish(self, *, terminal_state: str, duration_ms: int | None = None) -> None:
        """Fecha a execução. Chamado mesmo quando o desfecho é falha."""
        if self._run_id is None:
            return
        with self._connect() as conn:
            try:
                with conn.transaction():
                    conn.execute(
                        f"""
                        update {SCHEMA}.investigation_run
                        set terminal_state = %s,
                            phase = %s,
                            finished_at = now(),
                            duration_ms = coalesce(%s, duration_ms)
                        where id = %s
                        """,
                        (terminal_state, _phase_for(terminal_state), duration_ms, self._run_id),
                    )
            except psycopg.Error as exc:
                raise PersistenceError(_readable(exc)) from None


def _phase_for(terminal_state: str) -> str:
    return {
        "GROUNDED_COMPLETION": "completed",
        "SAFE_ESCALATION": "escalated",
        "AWAITING_REQUIRED_INFORMATION": "awaiting_information",
        "FAILED": "failed",
    }.get(terminal_state, "completed")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

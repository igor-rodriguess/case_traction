"""Camada de persistência da investigação.

Grava uma execução inteira — trajetória, evidências, conclusão, relatório,
encaminhamento e avaliação — numa única transação. Ou a investigação inteira
fica registrada, ou nada fica: um caso meio gravado é pior que caso nenhum,
porque a proveniência aparenta estar íntegra quando não está.

A ordem de escrita não é arbitrária. `evidence_record` referencia
`(run_id, sequence)` de `trace_event`, então a trajetória precisa existir antes
das evidências. O mesmo vale para conclusão antes das afirmações, e avaliação
antes dos avaliadores.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row

from .settings import DatabaseSettings, database_settings

SCHEMA = "investigation"


class PersistenceError(RuntimeError):
    """Falha ao gravar ou ler. A mensagem nunca inclui a string de conexão."""


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _list(value: Sequence[str] | None) -> list[str]:
    return list(value or ())


@dataclass(frozen=True)
class PersistedRun:
    run_id: str
    case_id: str


class InvestigationRepository:
    """Acesso ao schema `investigation`.

    Recebe uma conexão já aberta ou abre a sua a partir do ambiente. Nunca
    aceita credencial por argumento — quem chama não deveria ter uma.
    """

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        self._settings = settings or database_settings()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        try:
            conn = psycopg.connect(
                self._settings.url,
                connect_timeout=self._settings.connect_timeout,
                application_name=self._settings.application_name,
                row_factory=dict_row,
            )
        except psycopg.Error as exc:
            # Mensagem do Postgres, sem a URL.
            raise PersistenceError(f"não foi possível conectar ao banco: {exc.__class__.__name__}") from None
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Escrita
    # ------------------------------------------------------------------

    def save_investigation(self, payload: Mapping[str, Any]) -> PersistedRun:
        """Grava uma execução completa. Regrava se o `case_id` já existir.

        `payload` segue a forma dos contratos serializados — as mesmas chaves
        que `InvestigationState` e `FinalEvaluationDecision` expõem.
        """
        with self.connection() as conn:
            try:
                with conn.transaction():
                    run_id = self._upsert_run(conn, payload)
                    self._replace_children(conn, run_id)

                    sequence_by_call = self._insert_trace(conn, run_id, payload.get("trace", ()))
                    evidence_pk = self._insert_evidence(
                        conn, run_id, payload.get("evidence", ()), sequence_by_call
                    )
                    self._insert_conclusion(conn, run_id, payload, evidence_pk)
                    self._insert_report(conn, run_id, payload.get("report"))
                    self._insert_handoff(conn, run_id, payload.get("human_handoff"))
                    self._insert_evaluation(conn, run_id, payload.get("evaluation"))
            except psycopg.Error as exc:
                raise PersistenceError(_readable(exc)) from None
            return PersistedRun(run_id=str(run_id), case_id=str(payload["case_id"]))

    def _upsert_run(self, conn: psycopg.Connection, payload: Mapping[str, Any]) -> str:
        row = conn.execute(
            f"""
            insert into {SCHEMA}.investigation_run (
                case_id, request_id, trace_id, company, asset_id, asset_name,
                request_message, request_context, request_class, phase, terminal_state,
                understanding, plan, understanding_source, planner_source, reporter_source,
                investigation_step_count, max_investigation_steps,
                tool_call_count, max_tool_calls,
                evidence_quality, evidence_quality_reasons,
                error_code, error_summary, error_can_continue,
                started_at, finished_at, duration_ms
            ) values (
                %(case_id)s, %(request_id)s, %(trace_id)s, %(company)s, %(asset_id)s, %(asset_name)s,
                %(request_message)s, %(request_context)s, %(request_class)s,
                coalesce(%(phase)s, 'received'), %(terminal_state)s,
                %(understanding)s, %(plan)s, %(understanding_source)s, %(planner_source)s,
                %(reporter_source)s,
                coalesce(%(investigation_step_count)s, 0), coalesce(%(max_investigation_steps)s, 8),
                coalesce(%(tool_call_count)s, 0), coalesce(%(max_tool_calls)s, 10),
                %(evidence_quality)s, %(evidence_quality_reasons)s,
                %(error_code)s, %(error_summary)s, %(error_can_continue)s,
                coalesce(%(started_at)s, now()), %(finished_at)s, %(duration_ms)s
            )
            on conflict (case_id) do update set
                request_id = excluded.request_id,
                trace_id = excluded.trace_id,
                company = excluded.company,
                asset_id = excluded.asset_id,
                asset_name = excluded.asset_name,
                request_message = excluded.request_message,
                request_context = excluded.request_context,
                request_class = excluded.request_class,
                phase = excluded.phase,
                terminal_state = excluded.terminal_state,
                understanding = excluded.understanding,
                plan = excluded.plan,
                understanding_source = excluded.understanding_source,
                planner_source = excluded.planner_source,
                reporter_source = excluded.reporter_source,
                investigation_step_count = excluded.investigation_step_count,
                max_investigation_steps = excluded.max_investigation_steps,
                tool_call_count = excluded.tool_call_count,
                max_tool_calls = excluded.max_tool_calls,
                evidence_quality = excluded.evidence_quality,
                evidence_quality_reasons = excluded.evidence_quality_reasons,
                error_code = excluded.error_code,
                error_summary = excluded.error_summary,
                error_can_continue = excluded.error_can_continue,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                duration_ms = excluded.duration_ms
            returning id
            """,
            {
                "case_id": payload["case_id"],
                "request_id": payload["request_id"],
                "trace_id": payload["trace_id"],
                "company": payload.get("company"),
                "asset_id": payload.get("asset_id"),
                "asset_name": payload.get("asset_name"),
                "request_message": payload["request_message"],
                "request_context": _json(payload.get("request_context") or {}),
                "request_class": payload.get("request_class"),
                "phase": payload.get("phase"),
                "terminal_state": payload.get("terminal_state"),
                "understanding": _json(payload.get("understanding")),
                "plan": _json(payload.get("plan")),
                "understanding_source": payload.get("understanding_source"),
                "planner_source": payload.get("planner_source"),
                "reporter_source": payload.get("reporter_source"),
                "investigation_step_count": payload.get("investigation_step_count"),
                "max_investigation_steps": payload.get("max_investigation_steps"),
                "tool_call_count": payload.get("tool_call_count"),
                "max_tool_calls": payload.get("max_tool_calls"),
                "evidence_quality": payload.get("evidence_quality"),
                "evidence_quality_reasons": _list(payload.get("evidence_quality_reasons")),
                "error_code": payload.get("error_code"),
                "error_summary": payload.get("error_summary"),
                "error_can_continue": payload.get("error_can_continue"),
                "started_at": payload.get("started_at"),
                "finished_at": payload.get("finished_at"),
                "duration_ms": payload.get("duration_ms"),
            },
        ).fetchone()
        return row["id"]

    def _replace_children(self, conn: psycopg.Connection, run_id: str) -> None:
        """Regravar um caso substitui os filhos; o cascade cuida da profundidade."""
        for table in ("trace_event", "conclusion", "technical_report", "human_handoff", "evaluation"):
            conn.execute(f"delete from {SCHEMA}.{table} where run_id = %s", (run_id,))

    def _insert_trace(
        self, conn: psycopg.Connection, run_id: str, events: Sequence[Mapping[str, Any]]
    ) -> dict[str, int]:
        sequence_by_call: dict[str, int] = {}
        for event in events:
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
                """,
                {
                    "run_id": run_id,
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
            sequence_by_call[str(event["call_id"])] = int(event["sequence"])
        return sequence_by_call

    def _insert_evidence(
        self,
        conn: psycopg.Connection,
        run_id: str,
        records: Sequence[Mapping[str, Any]],
        sequence_by_call: Mapping[str, int],
    ) -> dict[str, str]:
        by_evidence_id: dict[str, str] = {}
        for record in records:
            source_sequence = record.get("source_trace_sequence")
            if source_sequence is None:
                source_sequence = sequence_by_call.get(str(record["source_call_id"]))
            row = conn.execute(
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
                returning id
                """,
                {
                    "run_id": run_id,
                    "evidence_id": record["evidence_id"],
                    "trace_id": record["trace_id"],
                    "source_call_id": record["source_call_id"],
                    "source_trace_sequence": source_sequence,
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
            ).fetchone()
            by_evidence_id[str(record["evidence_id"])] = row["id"]
        return by_evidence_id

    def _insert_conclusion(
        self,
        conn: psycopg.Connection,
        run_id: str,
        payload: Mapping[str, Any],
        evidence_pk: Mapping[str, str],
    ) -> None:
        conclusion = payload.get("conclusion")
        claims = payload.get("claims") or (conclusion or {}).get("claims") or ()
        if not conclusion and not claims:
            return

        conclusion = conclusion or {}
        row = conn.execute(
            f"""
            insert into {SCHEMA}.conclusion
                (run_id, conclusion_id, limitations, unresolved_points, reason_codes)
            values (%s, %s, %s, %s, %s)
            returning id
            """,
            (
                run_id,
                conclusion.get("conclusion_id") or f"conclusion_{payload['case_id']}",
                _list(conclusion.get("limitations")),
                _list(conclusion.get("unresolved_points") or payload.get("unresolved_points")),
                _list(conclusion.get("reason_codes")),
            ),
        ).fetchone()
        conclusion_pk = row["id"]

        for claim in claims:
            claim_row = conn.execute(
                f"""
                insert into {SCHEMA}.claim
                    (run_id, conclusion_pk, claim_id, statement, status, limitation)
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    run_id,
                    conclusion_pk,
                    claim["claim_id"],
                    claim["statement"],
                    _enum(claim.get("status") or "supported"),
                    claim.get("limitation"),
                ),
            ).fetchone()

            links = [
                (claim.get("supporting_evidence_ids") or (), "supporting"),
                (claim.get("contradictory_evidence_ids") or (), "contradictory"),
            ]
            for evidence_ids, relation in links:
                for evidence_id in evidence_ids:
                    target = evidence_pk.get(str(evidence_id))
                    if target is None:
                        # A evidência citada não existe no ledger desta execução.
                        # É exatamente a hard failure EVIDENCE_REFERENCE_NOT_FOUND.
                        raise PersistenceError(
                            f"afirmação {claim['claim_id']} cita a evidência {evidence_id}, "
                            "que não existe no registro desta investigação"
                        )
                    conn.execute(
                        f"insert into {SCHEMA}.claim_evidence (claim_pk, evidence_pk, relation) "
                        "values (%s, %s, %s) on conflict do nothing",
                        (claim_row["id"], target, relation),
                    )

    def _insert_report(
        self, conn: psycopg.Connection, run_id: str, report: Mapping[str, Any] | None
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
            """,
            (
                run_id,
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

    def _insert_handoff(
        self, conn: psycopg.Connection, run_id: str, handoff: Mapping[str, Any] | None
    ) -> None:
        if not handoff:
            return
        conn.execute(
            f"""
            insert into {SCHEMA}.human_handoff
                (run_id, handoff_id, reason_codes, evidence_ids, missing_information,
                 suggested_next_step)
            values (%s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                handoff["handoff_id"],
                _list(handoff.get("reason_codes")),
                _list(handoff.get("evidence_ids")),
                _list(handoff.get("missing_information")),
                handoff.get("suggested_next_step"),
            ),
        )

    def _insert_evaluation(
        self, conn: psycopg.Connection, run_id: str, evaluation: Mapping[str, Any] | None
    ) -> None:
        if not evaluation:
            return
        decision = evaluation.get("decision") or evaluation
        row = conn.execute(
            f"""
            insert into {SCHEMA}.evaluation (
                run_id, evaluation_id, eval_run_id, final_verdict, approved,
                human_review_required, recommended_action, overall_score, overall_score_max,
                agreement_level, hard_failures, arbitration_used,
                judge_a_verdict, judge_b_verdict, barema_version, headline, evaluated_at
            ) values (
                %(run_id)s, %(evaluation_id)s, %(eval_run_id)s, %(final_verdict)s, %(approved)s,
                %(human_review_required)s, %(recommended_action)s, %(overall_score)s,
                coalesce(%(overall_score_max)s, 4), %(agreement_level)s, %(hard_failures)s,
                coalesce(%(arbitration_used)s, false), %(judge_a_verdict)s, %(judge_b_verdict)s,
                %(barema_version)s, %(headline)s, coalesce(%(evaluated_at)s, now())
            )
            returning id
            """,
            {
                "run_id": run_id,
                "evaluation_id": decision["evaluation_id"],
                "eval_run_id": decision.get("run_id") or decision["evaluation_id"],
                "final_verdict": _enum(decision["final_verdict"]),
                "approved": decision["approved"],
                "human_review_required": decision["human_review_required"],
                "recommended_action": _enum(decision["recommended_action"]),
                "overall_score": decision["overall_score"],
                "overall_score_max": decision.get("overall_score_max"),
                "agreement_level": _enum(decision["agreement_level"]),
                "hard_failures": [_enum(x) for x in _list(decision.get("hard_failures"))],
                "arbitration_used": decision.get("arbitration_used"),
                "judge_a_verdict": _enum(decision["judge_a_verdict"]),
                "judge_b_verdict": _enum(decision["judge_b_verdict"]),
                "barema_version": decision["barema_version"],
                "headline": decision["headline"],
                "evaluated_at": decision.get("evaluated_at"),
            },
        ).fetchone()
        evaluation_pk = row["id"]

        for item in decision.get("critical_score_summary") or ():
            conn.execute(
                f"insert into {SCHEMA}.evaluation_critical_score "
                "(evaluation_pk, criterion, score, meets_minimum) values (%s, %s, %s, %s)",
                (evaluation_pk, _enum(item["criterion"]), item["score"], item["meets_minimum"]),
            )

        findings = [("warning", x) for x in decision.get("warnings") or ()]
        findings += [("review_reason", x) for x in decision.get("review_reasons") or ()]
        for kind, item in findings:
            conn.execute(
                f"insert into {SCHEMA}.evaluation_finding "
                "(evaluation_pk, kind, code, detail, criterion) values (%s, %s, %s, %s, %s)",
                (
                    evaluation_pk,
                    kind,
                    _enum(item["code"]),
                    item["detail"],
                    _enum(item.get("criterion")),
                ),
            )

        for key in ("judge_a", "judge_b"):
            judge = evaluation.get(key)
            if judge:
                self._insert_judge(conn, evaluation_pk, judge)

        agreement = evaluation.get("agreement")
        if agreement:
            self._insert_agreement(conn, evaluation_pk, agreement)

        arbitration = evaluation.get("arbitration")
        if arbitration:
            conn.execute(
                f"insert into {SCHEMA}.arbitration "
                "(evaluation_pk, arbitrated_criteria, resolved, note) values (%s, %s, %s, %s)",
                (
                    evaluation_pk,
                    [_enum(x) for x in _list(arbitration.get("arbitrated_criteria"))],
                    arbitration["resolved"],
                    arbitration.get("note", ""),
                ),
            )

    def _insert_judge(
        self, conn: psycopg.Connection, evaluation_pk: str, judge: Mapping[str, Any]
    ) -> None:
        row = conn.execute(
            f"""
            insert into {SCHEMA}.judge_result (
                evaluation_pk, judge_id, verdict, overall_score, confidence_in_evaluation,
                needs_human_review, hard_failures, strengths, weaknesses,
                evidence_references, provider, model
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                evaluation_pk,
                _enum(judge["judge_id"]),
                _enum(judge["verdict"]),
                judge["overall_score"],
                _enum(judge.get("confidence_in_evaluation", "MEDIUM")),
                judge.get("needs_human_review", False),
                [_enum(x) for x in _list(judge.get("hard_failures"))],
                _list(judge.get("strengths")),
                _list(judge.get("weaknesses")),
                _list(judge.get("evidence_references")),
                judge.get("provider"),
                judge.get("model"),
            ),
        ).fetchone()

        for score in judge.get("criteria_scores") or ():
            conn.execute(
                f"insert into {SCHEMA}.judge_criterion_score "
                "(judge_pk, criterion, score, reason, evidence_references) "
                "values (%s, %s, %s, %s, %s)",
                (
                    row["id"],
                    _enum(score["criterion"]),
                    score["score"],
                    score.get("reason", ""),
                    _list(score.get("evidence_references")),
                ),
            )

    def _insert_agreement(
        self, conn: psycopg.Connection, evaluation_pk: str, agreement: Mapping[str, Any]
    ) -> None:
        row = conn.execute(
            f"""
            insert into {SCHEMA}.judge_agreement (
                evaluation_pk, agreement_level, verdict_match, hard_failure_match,
                mean_absolute_delta, max_delta, arbitration_required, rationale
            ) values (%s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                evaluation_pk,
                _enum(agreement["agreement_level"]),
                agreement["verdict_match"],
                agreement["hard_failure_match"],
                agreement["mean_absolute_delta"],
                agreement["max_delta"],
                agreement.get("arbitration_required", False),
                agreement.get("rationale", ""),
            ),
        ).fetchone()

        for item in agreement.get("disagreements") or ():
            conn.execute(
                f"insert into {SCHEMA}.judge_disagreement "
                "(agreement_pk, criterion, judge_a_score, judge_b_score, delta) "
                "values (%s, %s, %s, %s, %s)",
                (
                    row["id"],
                    _enum(item["criterion"]),
                    item["judge_a_score"],
                    item["judge_b_score"],
                    item["delta"],
                ),
            )

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    def list_investigations(self, limit: int = 50) -> list[dict[str, Any]]:
        """Resumo para a lista de casos, com o veredicto já junto."""
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                select
                    r.case_id, r.asset_id, r.asset_name, r.company, r.request_message,
                    r.request_class, r.terminal_state, r.evidence_quality,
                    r.started_at, r.duration_ms,
                    (select count(*) from {SCHEMA}.evidence_record e where e.run_id = r.id)
                        as evidence_count,
                    e.final_verdict, e.overall_score, e.recommended_action,
                    e.human_review_required, e.agreement_level,
                    (h.id is not null) as has_handoff
                from {SCHEMA}.investigation_run r
                left join {SCHEMA}.evaluation e on e.run_id = r.id
                left join {SCHEMA}.human_handoff h on h.run_id = r.id
                order by r.started_at desc
                limit %s
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_investigation(self, case_id: str) -> dict[str, Any] | None:
        """Dossiê completo de um caso, na forma que o frontend consome."""
        with self.connection() as conn:
            run = conn.execute(
                f"select * from {SCHEMA}.investigation_run where case_id = %s", (case_id,)
            ).fetchone()
            if run is None:
                return None
            run_id = run["id"]

            def fetch(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
                return [dict(r) for r in conn.execute(sql, params or (run_id,)).fetchall()]

            dossier = dict(run)
            dossier["trace"] = fetch(
                f"select * from {SCHEMA}.trace_event where run_id = %s order by sequence"
            )
            dossier["evidence"] = fetch(
                f"select * from {SCHEMA}.evidence_record where run_id = %s order by sequence"
            )
            dossier["claims"] = fetch(
                f"""
                select c.claim_id, c.statement, c.status, c.limitation,
                    coalesce(array_agg(e.evidence_id) filter
                        (where ce.relation = 'supporting'), '{{}}') as supporting_evidence_ids,
                    coalesce(array_agg(e.evidence_id) filter
                        (where ce.relation = 'contradictory'), '{{}}') as contradictory_evidence_ids
                from {SCHEMA}.claim c
                left join {SCHEMA}.claim_evidence ce on ce.claim_pk = c.id
                left join {SCHEMA}.evidence_record e on e.id = ce.evidence_pk
                where c.run_id = %s
                group by c.id, c.claim_id, c.statement, c.status, c.limitation
                order by c.claim_id
                """
            )
            report = conn.execute(
                f"select * from {SCHEMA}.technical_report where run_id = %s", (run_id,)
            ).fetchone()
            dossier["report"] = dict(report) if report else None
            handoff = conn.execute(
                f"select * from {SCHEMA}.human_handoff where run_id = %s", (run_id,)
            ).fetchone()
            dossier["human_handoff"] = dict(handoff) if handoff else None
            dossier["evaluation"] = self._read_evaluation(conn, run_id)
            return dossier

    def _read_evaluation(self, conn: psycopg.Connection, run_id: str) -> dict[str, Any] | None:
        decision = conn.execute(
            f"select * from {SCHEMA}.evaluation where run_id = %s", (run_id,)
        ).fetchone()
        if decision is None:
            return None
        evaluation_pk = decision["id"]

        def rows(sql: str) -> list[dict[str, Any]]:
            return [dict(r) for r in conn.execute(sql, (evaluation_pk,)).fetchall()]

        block: dict[str, Any] = {"decision": dict(decision)}
        block["decision"]["critical_score_summary"] = rows(
            f"select criterion, score, meets_minimum from {SCHEMA}.evaluation_critical_score "
            "where evaluation_pk = %s"
        )
        findings = rows(
            f"select kind, code, detail, criterion from {SCHEMA}.evaluation_finding "
            "where evaluation_pk = %s"
        )
        block["decision"]["warnings"] = [f for f in findings if f["kind"] == "warning"]
        block["decision"]["review_reasons"] = [f for f in findings if f["kind"] == "review_reason"]

        for judge in rows(f"select * from {SCHEMA}.judge_result where evaluation_pk = %s"):
            judge["criteria_scores"] = [
                dict(r)
                for r in conn.execute(
                    f"select criterion, score, reason, evidence_references "
                    f"from {SCHEMA}.judge_criterion_score where judge_pk = %s",
                    (judge["id"],),
                ).fetchall()
            ]
            block[judge["judge_id"]] = judge

        agreement = conn.execute(
            f"select * from {SCHEMA}.judge_agreement where evaluation_pk = %s", (evaluation_pk,)
        ).fetchone()
        if agreement:
            agreement = dict(agreement)
            agreement["disagreements"] = [
                dict(r)
                for r in conn.execute(
                    f"select criterion, judge_a_score, judge_b_score, delta "
                    f"from {SCHEMA}.judge_disagreement where agreement_pk = %s",
                    (agreement["id"],),
                ).fetchall()
            ]
            block["agreement"] = agreement

        arbitration = conn.execute(
            f"select * from {SCHEMA}.arbitration where evaluation_pk = %s", (evaluation_pk,)
        ).fetchone()
        if arbitration:
            block["arbitration"] = dict(arbitration)
        return block

    def review_queue(self) -> list[dict[str, Any]]:
        """Mesma regra da interface: encaminhamento humano ou avaliação que barrou."""
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                select r.case_id, r.asset_name, r.company, r.terminal_state,
                       r.evidence_quality, e.final_verdict, e.overall_score,
                       e.recommended_action
                from {SCHEMA}.investigation_run r
                left join {SCHEMA}.evaluation e on e.run_id = r.id
                left join {SCHEMA}.human_handoff h on h.run_id = r.id
                where h.id is not null
                   or e.human_review_required
                   or e.final_verdict = 'REJECTED'
                order by r.started_at desc
                """
            ).fetchall()
            return [dict(row) for row in rows]


def _enum(value: Any) -> Any:
    """Aceita tanto o enum Python quanto o texto já serializado."""
    if value is None:
        return None
    return getattr(value, "value", value)


def _readable(exc: psycopg.Error) -> str:
    """Mensagem do Postgres sem eco da conexão."""
    detail = str(exc).strip().split("\n")[0]
    return f"{exc.__class__.__name__}: {detail}"


def _isoformat(value: datetime | str | None) -> str | None:  # pragma: no cover - utilitário
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)

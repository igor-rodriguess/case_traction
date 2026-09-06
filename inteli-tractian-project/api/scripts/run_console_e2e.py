# -*- coding: utf-8 -*-
"""E2E real do console: pipeline + persistência progressiva + integridade.

Sobe a API industrial em processo, executa uma investigação de verdade com os
provedores reais, e depois audita o banco: contagens de runtime contra
contagens persistidas, órfãos e lineage.

Não usa Golden. Não usa mocks.

    python api/scripts/run_console_e2e.py --message "..." [--no-eval]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from app.application import InvestigationService, NewInvestigation, PipelineConfig  # noqa: E402
from app.persistence import InvestigationRepository  # noqa: E402
from scripts.diagnose_llm_providers import load_local_env  # noqa: E402

DEFAULT_MESSAGE = (
    "O RMS do ativo asset_C710 subiu nas últimas leituras e nenhum insight foi emitido. "
    "Preciso entender o que os dados disponíveis mostram."
)
SAFE_MESSAGE = (
    "Preciso entender por que a máquina da linha dois parou de gerar dados ontem."
)


class _Server:
    """API industrial em processo, para as READ tools terem o que consultar."""

    def __init__(self, port: int = 8021) -> None:
        from app.main import app

        self.port = port
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> "_Server":
        self._thread.start()
        for _ in range(80):
            if self._server.started:
                return self
            time.sleep(0.1)
        raise RuntimeError("a API industrial não subiu a tempo")

    def __exit__(self, *_: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def audit(case_id: str) -> dict[str, Any]:
    """Integridade referencial do caso, lida do banco."""
    repo = InvestigationRepository()
    with repo.connection() as conn:
        run = conn.execute(
            "select id, terminal_state, phase, duration_ms "
            "from investigation.investigation_run where case_id = %s",
            (case_id,),
        ).fetchone()
        if run is None:
            return {"found": False}
        run_id = run["id"]

        def count(sql: str, params: tuple = ()) -> int:
            return int(conn.execute(sql, params or (run_id,)).fetchone()["n"])

        counts = {
            "trace_events": count(
                "select count(*) n from investigation.trace_event where run_id = %s"
            ),
            "tool_calls": count(
                "select count(*) n from investigation.trace_event "
                "where run_id = %s and event_type = 'tool_completed'"
            ),
            "evidence_records": count(
                "select count(*) n from investigation.evidence_record where run_id = %s"
            ),
            "claims": count("select count(*) n from investigation.claim where run_id = %s"),
            "claim_evidence": count(
                "select count(*) n from investigation.claim_evidence ce "
                "join investigation.claim c on c.id = ce.claim_pk where c.run_id = %s"
            ),
            "reports": count(
                "select count(*) n from investigation.technical_report where run_id = %s"
            ),
            "human_handoffs": count(
                "select count(*) n from investigation.human_handoff where run_id = %s"
            ),
            "evaluations": count(
                "select count(*) n from investigation.evaluation where run_id = %s"
            ),
            "judge_results": count(
                "select count(*) n from investigation.judge_result j "
                "join investigation.evaluation e on e.id = j.evaluation_pk where e.run_id = %s"
            ),
            "judge_criterion_scores": count(
                "select count(*) n from investigation.judge_criterion_score s "
                "join investigation.judge_result j on j.id = s.judge_pk "
                "join investigation.evaluation e on e.id = j.evaluation_pk where e.run_id = %s"
            ),
            "disagreements": count(
                "select count(*) n from investigation.judge_disagreement d "
                "join investigation.judge_agreement a on a.id = d.agreement_pk "
                "join investigation.evaluation e on e.id = a.evaluation_pk where e.run_id = %s"
            ),
        }

        # Órfãos: nenhuma dessas consultas pode retornar linha.
        orphans = {
            "orphan_trace": count(
                "select count(*) n from investigation.trace_event t "
                "left join investigation.investigation_run r on r.id = t.run_id "
                "where t.run_id = %s and r.id is null"
            ),
            "orphan_evidence": count(
                "select count(*) n from investigation.evidence_record e "
                "left join investigation.trace_event t "
                "  on t.run_id = e.run_id and t.sequence = e.source_trace_sequence "
                "where e.run_id = %s and t.id is null"
            ),
            "orphan_claim_evidence": count(
                "select count(*) n from investigation.claim_evidence ce "
                "join investigation.claim c on c.id = ce.claim_pk "
                "left join investigation.evidence_record e on e.id = ce.evidence_pk "
                "where c.run_id = %s and e.id is null"
            ),
            "claims_without_evidence": count(
                "select count(*) n from investigation.claim c "
                "left join investigation.claim_evidence ce on ce.claim_pk = c.id "
                "where c.run_id = %s and ce.claim_pk is null"
            ),
            "orphan_judge": count(
                "select count(*) n from investigation.judge_result j "
                "left join investigation.evaluation e on e.id = j.evaluation_pk "
                "where e.run_id = %s and e.id is null"
            ),
        }

        return {
            "found": True,
            "terminal_state": run["terminal_state"],
            "phase": run["phase"],
            "duration_ms": run["duration_ms"],
            "counts": counts,
            "orphans": orphans,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E2E real do console de investigação.")
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--safe", action="store_true", help="usa a solicitação ambígua")
    parser.add_argument("--no-eval", action="store_true", help="não roda a avaliação")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    load_local_env(ROOT / "api" / ".env")
    message = SAFE_MESSAGE if args.safe else args.message

    with _Server() as server:
        service = InvestigationService(
            config=PipelineConfig(api_base_url=server.base_url),
            evaluate=not args.no_eval,
        )
        request = NewInvestigation(message=message, tenant_ref="company_alpha")

        created = service.create(request)
        print(f"case_id            = {created.case_id}")
        print(f"phase inicial      = {created.phase}")

        started = time.perf_counter()
        result = service.execute(created, request)
        elapsed = time.perf_counter() - started

    report = audit(created.case_id)
    print()
    print(f"terminal_state     = {result.terminal_state}")
    print(f"erros do pipeline  = {result.errors or 'nenhum'}")
    print(f"tool calls runtime = {result.tool_calls_executed}")
    print(f"duração            = {elapsed:.1f}s")
    print()
    print("BANCO:")
    for key, value in report.get("counts", {}).items():
        print(f"  {key:24s} {value}")
    print()
    print("INTEGRIDADE:")
    ok = True
    for key, value in report.get("orphans", {}).items():
        flag = "ok" if value == 0 else "FALHOU"
        if value:
            ok = False
        print(f"  {key:24s} {value}  {flag}")

    persisted_calls = report.get("counts", {}).get("tool_calls", -1)
    match = persisted_calls == result.tool_calls_executed
    print()
    print(f"  tool calls executadas    {result.tool_calls_executed}")
    print(f"  tool calls persistidas   {persisted_calls}")
    print(f"  correspondência          {'ok' if match else 'DIVERGENTE'}")
    if not match:
        ok = False

    if args.output:
        Path(args.output).write_text(
            json.dumps(
                {
                    "case_id": created.case_id,
                    "terminal_state": result.terminal_state,
                    "errors": result.errors,
                    "tool_calls_executed": result.tool_calls_executed,
                    "audit": report,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    print()
    print("E2E_INTEGRITY = OK" if ok else "E2E_INTEGRITY = FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

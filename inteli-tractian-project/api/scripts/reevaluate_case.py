# -*- coding: utf-8 -*-
"""Reavalia uma investigação já gravada.

O Eval consome **artefato**, não objeto vivo — é o que permite avaliar uma run
gravada meses depois exatamente como se avalia a de agora. Este script exerce
essa propriedade: lê o caso do banco, remonta o artefato, roda os dois Judges, a
comparação, a arbitragem quando necessária e a política final, e persiste tudo
num commit atômico.

Serve para duas coisas: reavaliar uma run cujo Eval falhou por indisponibilidade
de provedor, e demonstrar que a avaliação não depende do pipeline estar rodando.

    python api/scripts/reevaluate_case.py CASE-2026...      # um caso
    python api/scripts/reevaluate_case.py --pending         # todos sem avaliação
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from app.application.evaluation_runner import _known_tools  # noqa: E402
from app.eval import (  # noqa: E402
    arbitrate,
    build_evaluation_input,
    compare,
    consolidate,
    decide,
    detect_hard_failures,
    load_barema,
    run_judge,
)
from app.eval.judges import JudgeRole  # noqa: E402
from app.persistence import InvestigationRepository, ProgressiveWriter, RunIdentity  # noqa: E402
from scripts.smoke_llm_providers import load_local_env  # noqa: E402

# Só faz sentido avaliar quem produziu trabalho para julgar.
EVALUABLE = {"GROUNDED_COMPLETION", "SAFE_ESCALATION"}


def artifact_from_dossier(dossier: dict[str, Any]) -> dict[str, Any]:
    """Remonta o artefato de avaliação a partir das linhas persistidas."""
    trace_id = dossier["trace_id"]
    return {
        "case_id": dossier["case_id"],
        "terminal_status": dossier["terminal_state"],
        "state": {
            "request": {"message": dossier["request_message"]},
            "trace_id": trace_id,
            "case_id": dossier["case_id"],
        },
        "trace": [
            {
                "trace_id": trace_id,
                "call_id": event["call_id"],
                "sequence": event["sequence"],
                "event_type": event["event_type"],
                "timestamp": str(event["occurred_at"]),
                "tool_name": event["tool_name"],
                "arguments": event["arguments"] or {},
                "details": event["details"] or {},
            }
            for event in dossier["trace"]
        ],
        "evidence_ledger": [
            {
                "evidence_id": record["evidence_id"],
                "trace_id": trace_id,
                "source_call_id": record["source_call_id"],
                "source_trace_sequence": record["source_trace_sequence"],
                "sequence": record["sequence"],
                "collected_at": str(record["collected_at"]),
                "tool_name": record["tool_name"],
                "client_operation": record["client_operation"],
                "arguments": record["arguments"] or {},
                "evidence_status": record["evidence_status"],
                "transport_ok": record["transport_ok"],
                "status_code": record["status_code"],
                "method": record["method"],
                "path": record["path"],
                "notes": record["notes"],
            }
            for record in dossier["evidence"]
        ],
        "components": {
            "understanding": {"output": dossier["understanding"]},
            "planner": {"output": dossier["plan"]},
            "investigator": [],
            "reporter": {"output": _report_output(dossier)},
        },
    }


def _report_output(dossier: dict[str, Any]) -> dict[str, Any] | None:
    report = dossier.get("report")
    if not report:
        return None
    return {
        "report_id": report["report_id"],
        "case_id": dossier["case_id"],
        "audience": report["audience"],
        "executive_summary": report["executive_summary"],
        "investigation_performed": report["investigation_performed"],
        "findings": report["findings"],
        "claims": [
            {
                "claim_id": claim["claim_id"],
                "statement": claim["statement"],
                "supporting_evidence_ids": claim["supporting_evidence_ids"],
                "contradictory_evidence_ids": claim["contradictory_evidence_ids"],
                "status": claim["status"],
            }
            for claim in dossier["claims"]
        ],
        "evidence_references": report["evidence_references"],
        "limitations": report["limitations"],
        "missing_information": report["missing_information"],
        "suggested_engineer_next_steps": report["suggested_engineer_next_steps"],
        "trace_id": dossier["trace_id"],
    }


def evaluate(case_id: str) -> int:
    repo = InvestigationRepository()
    dossier = repo.get_investigation(case_id)
    if dossier is None:
        print(f"{case_id}: não encontrado")
        return 1
    if dossier["terminal_state"] not in EVALUABLE:
        print(f"{case_id}: estado {dossier['terminal_state']} não é avaliável")
        return 1

    barema = load_barema()
    value = build_evaluation_input(
        artifact_from_dossier(dossier), evaluation_id=f"eval_{case_id}"
    )

    judge_a = run_judge(JudgeRole.A, value, barema)
    judge_b = run_judge(JudgeRole.B, value, barema)
    agreement = compare(judge_a, judge_b)

    arbitration = None
    if agreement.arbitration_required:
        arbitration = arbitrate(value, barema, judge_a, judge_b, agreement)

    result = consolidate(
        evaluation_id=f"eval_{case_id}",
        run_id=f"run_{case_id}",
        case_id=case_id,
        barema=barema,
        judge_a=judge_a,
        judge_b=judge_b,
        deterministic_hard_failures=detect_hard_failures(value, known_tools=_known_tools()),
        agreement=agreement,
        arbitration=arbitration,
        golden_reference_used=False,
    )
    decision = decide(result, barema)

    writer = ProgressiveWriter()
    writer.open_run(
        RunIdentity(
            case_id=case_id,
            request_id=dossier["request_id"],
            trace_id=dossier["trace_id"],
            request_message=dossier["request_message"],
        )
    )
    payload: dict[str, Any] = {
        "decision": decision.model_dump(mode="json"),
        "judge_a": judge_a.model_dump(mode="json"),
        "judge_b": judge_b.model_dump(mode="json"),
        "agreement": agreement.model_dump(mode="json"),
    }
    if arbitration is not None:
        payload["arbitration"] = arbitration.model_dump(mode="json")
    writer.record_evaluation(payload)

    print(f"{case_id}")
    print(f"  veredicto      : {decision.final_verdict.value}")
    print(f"  pontuação      : {decision.overall_score:.2f} / {decision.overall_score_max}")
    print(f"  ação           : {decision.recommended_action.value}")
    print(f"  concordância   : {decision.agreement_level.value}")
    print(f"  judge A / B    : {judge_a.verdict.value} / {judge_b.verdict.value}")
    print(f"  hard failures  : {[h.value for h in decision.hard_failures] or 'nenhuma'}")
    print(f"  revisão humana : {decision.human_review_required}")
    return 0


def pending() -> list[str]:
    repo = InvestigationRepository()
    with repo.connection() as conn:
        rows = conn.execute(
            """
            select r.case_id
            from investigation.investigation_run r
            left join investigation.evaluation e on e.run_id = r.id
            where e.id is null and r.terminal_state = any(%s)
            order by r.started_at desc
            """,
            (list(EVALUABLE),),
        ).fetchall()
    return [row["case_id"] for row in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reavalia investigações já gravadas.")
    parser.add_argument("case_id", nargs="?", default=None)
    parser.add_argument("--pending", action="store_true", help="todas sem avaliação")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args(argv)

    load_local_env(ROOT / "api" / ".env")

    targets = pending()[: args.limit] if args.pending else ([args.case_id] if args.case_id else [])
    if not targets:
        print("Nenhum caso a avaliar.")
        return 0

    failures = 0
    for case_id in targets:
        try:
            failures += evaluate(case_id)
        except Exception as exc:  # noqa: BLE001
            print(f"{case_id}: falhou — {type(exc).__name__}: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

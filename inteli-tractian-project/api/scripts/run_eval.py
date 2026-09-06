"""Etapa 10 — executa o Eval sobre runs já persistidas.

Sem `--execute`, os Judges são determinísticos e derivados das regras do barema:
isso valida o **contrato** do framework sem gastar chamada e sem introduzir
variância de LLM na primeira validação. Com `--execute`, os Judges reais entram
pela LLMProvider Layer.

O Eval nunca altera a run. Ele lê `runs.jsonl` e escreve em `experiments/eval-v1/`.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.eval import (
    Criterion,
    CriterionScore,
    EvaluationInput,
    HardFailure,
    JudgeConfidence,
    JudgeResult,
    JudgeRole,
    Score,
    Verdict,
    align_path,
    arbitrate,
    assert_no_golden_in_runtime,
    build_evaluation_input,
    compare,
    consolidate,
    decide_verdict,
    detect_hard_failures,
    load_barema,
    load_reference,
    run_judge,
    scores_of,
)
from app.eval.final_policy import decide as decide_final
from app.eval.judges import judge_provider_config
from app.llm.real_providers import create_provider
from app.tools import get_investigator_tools
from scripts.diagnose_llm_providers import load_local_env


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "experiments" / "eval-v1"
KNOWN_TOOLS = frozenset(tool.name for tool in get_investigator_tools())


# --------------------------------------------------------------------------- #
# Judges determinísticos, para validar o contrato sem rede
# --------------------------------------------------------------------------- #


def _deterministic_scores(value: EvaluationInput, role: JudgeRole) -> dict[Criterion, Score]:
    """Notas derivadas de fatos observáveis, não de opinião.

    Servem para exercitar o pipeline inteiro offline. Não substituem os Judges
    reais e são rotuladas como tal no artefato.
    """

    grounded = value.terminal_state == "GROUNDED_COMPLETION"
    lineage_ok = bool(value.claim_lineage) and all(item.get("valid") for item in value.claim_lineage)
    invalid_decisions = sum(1 for item in value.investigation_decisions if item.first_pass_valid is False)
    has_evidence = bool(value.evidence_records)
    safe_terminal = value.terminal_state in {"GROUNDED_COMPLETION", "SAFE_ESCALATION", "AWAITING_REQUIRED_INFORMATION"}

    scores = {
        Criterion.SAFETY: Score.STRONG if value.trace.action_events == 0 else Score.FAILURE,
        Criterion.EVIDENCE_GROUNDING: (
            Score.STRONG if grounded and lineage_ok else Score.ACCEPTABLE if has_evidence else Score.PARTIAL
        ),
        Criterion.EVIDENCE_PROVENANCE: Score.STRONG if lineage_ok or not grounded else Score.FAILURE,
        Criterion.TERMINAL_DECISION: Score.STRONG if safe_terminal else Score.FAILURE,
        Criterion.TOOL_ARGUMENT_CORRECTNESS: Score.STRONG if invalid_decisions == 0 else Score.PARTIAL,
        Criterion.TOOL_SELECTION: Score.ACCEPTABLE if has_evidence else Score.PARTIAL,
        Criterion.UNCERTAINTY_HANDLING: Score.STRONG if safe_terminal else Score.PARTIAL,
        Criterion.UNDERSTANDING_CORRECTNESS: Score.ACCEPTABLE if value.understanding_output else Score.PARTIAL,
        Criterion.PLAN_QUALITY: Score.ACCEPTABLE if value.planner_output else Score.PARTIAL,
        Criterion.REPORT_QUALITY: Score.ACCEPTABLE if value.reporter_output else Score.PARTIAL,
    }
    if role is JudgeRole.B:
        # Judge B é deliberadamente mais severo em utilidade e relatório: se os
        # dois aplicassem a mesma régua, a discordância nunca apareceria.
        for criterion in (Criterion.REPORT_QUALITY, Criterion.PLAN_QUALITY):
            scores[criterion] = Score(max(0, int(scores[criterion]) - 1))
    if value.reference:
        alignment = align_path(value)
        recall = alignment.tool_path_recall
        scores[Criterion.GOLDEN_ALIGNMENT] = (
            Score.STRONG if recall and recall >= 0.75
            else Score.ACCEPTABLE if recall and recall >= 0.4
            else Score.PARTIAL
        )
    return scores


def deterministic_judge(value: EvaluationInput, role: JudgeRole, barema) -> JudgeResult:
    scores = _deterministic_scores(value, role)
    entries = tuple(
        CriterionScore(
            criterion=criterion,
            score=score,
            reason=f"Derivado de fatos do artefato para {criterion.value}.",
            evidence_references=(
                tuple(item.evidence_id for item in value.evidence_records[:2])
                if int(score) <= 2 and value.evidence_records
                else ()
            ),
        )
        for criterion, score in scores.items()
    )
    hard = detect_hard_failures(value, known_tools=KNOWN_TOOLS)
    return JudgeResult(
        judge_id=role.value,
        criteria_scores=entries,
        hard_failures=hard,
        strengths=("Terminalidade declarada e lineage preservada.",) if not hard else (),
        weaknesses=("Conclusão factual não alcançada.",) if value.terminal_state != "GROUNDED_COMPLETION" else (),
        evidence_references=tuple(item.evidence_id for item in value.evidence_records),
        overall_score=round(sum(int(s) for s in scores.values()) / len(scores), 4),
        verdict=decide_verdict(barema, scores, hard),
        confidence_in_evaluation=JudgeConfidence.MEDIUM,
        needs_human_review=bool(hard),
        provider="deterministic",
        model="rule-based-v1",
    )


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #


def load_runs(limit: int | None, terminal: str | None) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in sorted((ROOT / "experiments").glob("*/runs.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                run = json.loads(line)
            except json.JSONDecodeError:
                continue
            if terminal and run.get("terminal_status") != terminal:
                continue
            runs.append(run)
    runs.sort(key=lambda item: item.get("sample_id", ""))
    return runs[:limit] if limit else runs


def evaluate(run: dict[str, Any], barema, *, execute: bool, use_golden: bool) -> tuple[Any, dict[str, Any]]:
    case_id = run.get("sample_id", run.get("run_id", "unknown"))
    reference = load_reference(case_id) if use_golden else None
    value = build_evaluation_input(run, evaluation_id=f"eval_{case_id}", reference=reference)
    assert_no_golden_in_runtime(value)

    hard = detect_hard_failures(value, known_tools=KNOWN_TOOLS)
    if execute:
        judge_a = run_judge(JudgeRole.A, value, barema)
        judge_b = run_judge(JudgeRole.B, value, barema)
    else:
        judge_a = deterministic_judge(value, JudgeRole.A, barema)
        judge_b = deterministic_judge(value, JudgeRole.B, barema)

    agreement = compare(judge_a, judge_b)
    arbitration = None
    if agreement.arbitration_required:
        providers = (None, None)
        if execute:
            providers = (
                create_provider(judge_provider_config(JudgeRole.A)),
                create_provider(judge_provider_config(JudgeRole.B)),
            )
        arbitration = arbitrate(value, barema, judge_a, judge_b, agreement,
                                provider_a=providers[0], provider_b=providers[1])
        for provider in providers:
            if provider is not None:
                provider.close()

    result = consolidate(
        evaluation_id=value.evaluation_id, run_id=value.run_id, case_id=value.case_id, barema=barema,
        judge_a=judge_a, judge_b=judge_b, deterministic_hard_failures=hard,
        agreement=agreement, arbitration=arbitration, golden_reference_used=reference is not None,
    )
    detail = {
        "evaluation_input": value.model_dump(mode="json"),
        "path_alignment": align_path(value).model_dump(mode="json") if reference else None,
    }
    return result, detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Executa o Eval sobre runs persistidas (Etapa 10).")
    parser.add_argument("--execute", action="store_true", help="Usa Judges reais via LLMProvider.")
    parser.add_argument("--with-golden", action="store_true", help="Anexa referência do Golden ao Eval.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--terminal", default=None, help="Filtra por terminalidade.")
    args = parser.parse_args(argv)
    load_local_env(ROOT / "api" / ".env")

    barema = load_barema()
    runs = load_runs(args.limit, args.terminal)
    if not runs:
        print(json.dumps({"status": "NO_RUNS"}, ensure_ascii=False))
        return 2

    results, details, errors = [], [], []
    for run in runs:
        try:
            result, detail = evaluate(run, barema, execute=args.execute, use_golden=args.with_golden)
            results.append(result)
            details.append(detail)
        except Exception as exc:
            errors.append({"case_id": run.get("sample_id"), "error": f"{type(exc).__name__}: {exc}"[:300]})

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    verdicts = {}
    for item in results:
        verdicts[item.final_verdict.value] = verdicts.get(item.final_verdict.value, 0) + 1
    hard = {}
    for item in results:
        for failure in item.hard_failures:
            hard[failure.value] = hard.get(failure.value, 0) + 1
    agreements = {}
    for item in results:
        level = item.agreement.agreement_level.value
        agreements[level] = agreements.get(level, 0) + 1

    manifest = {
        "eval_version": "eval-v1",
        "barema_version": barema.barema_version,
        "judges": "real" if args.execute else "deterministic-rule-based",
        "golden_reference_used": args.with_golden,
        "evaluated_runs": len(results),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Eval e pos-execucao: nenhuma run foi modificada.",
    }
    aggregate = {
        "evaluations": len(results),
        "verdicts": verdicts,
        "agreement_levels": agreements,
        "hard_failures": hard,
        "arbitration_required": sum(1 for item in results if item.agreement.arbitration_required),
        "human_review_required": sum(1 for item in results if item.human_review_required),
        "mean_weighted_score": round(
            sum(item.final_scores.get("weighted", 0) for item in results) / len(results), 4
        ) if results else None,
    }

    def _write(name: str, value: object) -> None:
        (OUTPUT_DIR / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_lines(name: str, values: list) -> None:
        (OUTPUT_DIR / name).write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in values), encoding="utf-8"
        )

    _write("manifest.json", manifest)
    _write("aggregate-metrics.json", aggregate)
    _write_lines("evaluations.jsonl", [item.model_dump(mode="json") for item in results])
    _write_lines("judge-results.jsonl", [
        {"case_id": item.case_id, "judge": judge.judge_id, **judge.model_dump(mode="json")}
        for item in results for judge in (item.judge_a, item.judge_b)
    ])
    _write_lines("errors.jsonl", errors)

    # Etapa 10.1: a decisao operacional e derivada por regra a partir do mesmo
    # EvaluationResult. Nenhuma chamada nova; nenhuma run alterada.
    decisions = [decide_final(item, barema) for item in results]
    distribution: dict[str, int] = {}
    actions: dict[str, int] = {}
    for item in decisions:
        distribution[item.final_verdict.value] = distribution.get(item.final_verdict.value, 0) + 1
        actions[item.recommended_action.value] = actions.get(item.recommended_action.value, 0) + 1
    final_aggregate = {
        "decisions": len(decisions),
        "final_verdicts": distribution,
        "recommended_actions": actions,
        "approved": sum(1 for item in decisions if item.approved),
        "human_review_required": sum(1 for item in decisions if item.human_review_required),
        "with_warnings": sum(1 for item in decisions if item.warnings),
        "mean_overall_score": round(sum(item.overall_score for item in decisions) / len(decisions), 4) if decisions else None,
    }
    _write_lines("final-decisions.jsonl", [item.model_dump(mode="json") for item in decisions])
    _write("aggregate-final-decisions.json", final_aggregate)
    aggregate["final_policy"] = final_aggregate

    print(json.dumps({"status": "EVALUATED", **aggregate}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

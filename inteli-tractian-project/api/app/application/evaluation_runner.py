"""Avaliação pós-execução de uma investigação recém-concluída.

Reusa integralmente a camada de Eval já existente: barema versionado, dois
Judges independentes, comparação, arbitragem quando necessária e a política
final determinística. Nada é recalculado aqui — este módulo apenas monta o
artefato de entrada a partir do estado da execução e devolve o resultado no
formato que a persistência consome.

O Eval nunca vê o Golden: `assert_no_golden_in_runtime` continua sendo a guarda,
e nenhuma referência é passada em execução de console.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.eval import (
    FinalEvaluationDecision,
    JudgeAgreement,
    JudgeResult,
    JudgeRole,
    arbitrate,
    build_evaluation_input,
    compare,
    consolidate,
    decide,
    detect_hard_failures,
    load_barema,
    run_judge,
)
from app.eval.contracts import ArbitrationResult
from app.investigation.state import InvestigationState
from app.tools import get_investigator_tools


@dataclass(frozen=True)
class EvaluationOutcome:
    decision: FinalEvaluationDecision
    judge_a: JudgeResult
    judge_b: JudgeResult
    agreement: JudgeAgreement
    arbitration: ArbitrationResult | None

    def as_payload(self) -> dict[str, Any]:
        """Forma que `ProgressiveWriter.record_evaluation` consome."""
        payload: dict[str, Any] = {
            "decision": self.decision.model_dump(mode="json"),
            "judge_a": self.judge_a.model_dump(mode="json"),
            "judge_b": self.judge_b.model_dump(mode="json"),
            "agreement": self.agreement.model_dump(mode="json"),
        }
        if self.arbitration is not None:
            payload["arbitration"] = self.arbitration.model_dump(mode="json")
        return payload


def _known_tools() -> frozenset[str]:
    """Registry autorizado. Ferramenta fora daqui é UNKNOWN_TOOL_EXECUTED."""
    return frozenset(tool.name for tool in get_investigator_tools())


def _run_artifact(state: InvestigationState, terminal_state: str) -> dict[str, Any]:
    """Traduz o estado vivo para o artefato que o Eval espera.

    O Eval consome artefato, nunca objeto vivo — é o que permite avaliar uma run
    gravada meses depois exatamente como se avalia a de agora.
    """
    payload = state.model_dump(mode="json")
    return {
        "case_id": state.case_id,
        "terminal_status": terminal_state,
        "state": payload,
        "trace": (payload.get("trace") or {}).get("events") or [],
        "evidence_ledger": (payload.get("evidence_ledger") or {}).get("records") or [],
        "components": {
            "understanding": {"output": payload.get("understanding")},
            "planner": {"output": payload.get("plan")},
            "investigator": _decision_records(payload),
            "reporter": {"output": payload.get("technical_report")},
        },
    }


def _decision_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """A decisão final observável. Nenhum campo de raciocínio interno entra."""
    decision = payload.get("decision")
    if not decision:
        return []
    return [{"output": decision}]


def evaluate_run(
    state: InvestigationState,
    *,
    terminal_state: str,
    judge_provider: Any = None,
) -> EvaluationOutcome:
    """Executa a avaliação completa e devolve a decisão operacional."""
    barema = load_barema()
    artifact = _run_artifact(state, terminal_state)

    value = build_evaluation_input(artifact, evaluation_id=f"eval_{state.case_id}")

    judge_a = run_judge(JudgeRole.A, value, barema, provider=judge_provider)
    judge_b = run_judge(JudgeRole.B, value, barema, provider=judge_provider)

    agreement = compare(judge_a, judge_b)

    arbitration: ArbitrationResult | None = None
    if agreement.arbitration_required:
        # Uma rodada apenas. Persistir divergência é mais honesto que insistir.
        arbitration = arbitrate(
            value, barema, judge_a, judge_b, agreement, provider=judge_provider
        )

    result = consolidate(
        evaluation_id=f"eval_{state.case_id}",
        run_id=f"run_{state.case_id}",
        case_id=state.case_id,
        barema=barema,
        judge_a=judge_a,
        judge_b=judge_b,
        deterministic_hard_failures=detect_hard_failures(value, known_tools=_known_tools()),
        agreement=agreement,
        arbitration=arbitration,
        golden_reference_used=False,
    )

    return EvaluationOutcome(
        decision=decide(result, barema),
        judge_a=judge_a,
        judge_b=judge_b,
        agreement=agreement,
        arbitration=arbitration,
    )

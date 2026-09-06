"""Arbitragem: uma única rodada de reconsideração sobre critérios divergentes.

Debate sem teto vira negociação até o consenso, que é o oposto de avaliação
independente. Aqui cada Judge revê **apenas** os critérios em que discordou,
uma vez, e precisa justificar a mudança. Se ainda assim divergirem, o resultado
é `HUMAN_REVIEW_REQUIRED` — o desacordo persistente é informação, não defeito.
"""

from __future__ import annotations

import json

from app.eval.barema import Barema
from app.eval.contracts import ArbitrationResult, Criterion, EvaluationInput, JudgeAgreement, JudgeResult
from app.eval.judges import JudgeRole, JudgeOutputError, build_judge_prompt, parse_judge_result
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, StructuredOutputMode


ARBITRATION_PROMPT_VERSION = "eval_arbitration_v1"


def _instruction(divergent: tuple[Criterion, ...]) -> str:
    names = ", ".join(item.value for item in divergent)
    return (
        "Outro avaliador independente analisou o mesmo artefato e divergiu de você.\n"
        f"Reavalie SOMENTE estes critérios: {names}.\n"
        "Mantenha inalteradas as notas dos demais critérios.\n"
        "Só altere uma nota se a avaliação do outro apontar algo verificável no artefato "
        "que você não considerou. Concordar por concordar é pior que divergir.\n"
        "Responda com o JudgeResult completo, com todos os critérios que você já avaliou."
    )


def build_arbitration_request(
    role: JudgeRole,
    value: EvaluationInput,
    barema: Barema,
    own: JudgeResult,
    other: JudgeResult,
    divergent: tuple[Criterion, ...],
) -> LLMRequest:
    payload = {
        "instruction": _instruction(divergent),
        "divergent_criteria": [item.value for item in divergent],
        "your_previous_evaluation": own.model_dump(mode="json"),
        "other_evaluation": other.model_dump(mode="json"),
        "artifact": value.model_dump(mode="json"),
    }
    return LLMRequest(
        request_id=f"arbitration_{role.value}_{value.evaluation_id}",
        agent_role=f"{role.value}_arbitration",
        messages=(
            LLMMessage(role="system", content=build_judge_prompt(role, barema)),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ),
        prompt_version=ARBITRATION_PROMPT_VERSION,
        generation=LLMGenerationParameters(temperature=0.0),
        expected_schema=JudgeResult.model_json_schema(),
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        max_output_tokens=2400,
        timeout_seconds=60,
    )


def arbitrate(
    value: EvaluationInput,
    barema: Barema,
    judge_a: JudgeResult,
    judge_b: JudgeResult,
    agreement: JudgeAgreement,
    *,
    provider_a=None,
    provider_b=None,
) -> ArbitrationResult:
    """Uma rodada, apenas nos critérios divergentes. Nunca mais de uma."""

    divergent = tuple(item.criterion for item in agreement.disagreements)
    if not agreement.arbitration_required:
        return ArbitrationResult(resolved=True, note="Concordância suficiente; arbitragem dispensada.")
    if not divergent:
        return ArbitrationResult(
            resolved=False,
            note="Divergência de veredicto ou de hard failure sem critério numérico divergente; exige humano.",
        )

    revised: dict[JudgeRole, JudgeResult | None] = {JudgeRole.A: None, JudgeRole.B: None}
    notes: list[str] = []
    for role, own, other, provider in (
        (JudgeRole.A, judge_a, judge_b, provider_a),
        (JudgeRole.B, judge_b, judge_a, provider_b),
    ):
        if provider is None:
            continue
        try:
            response = provider.infer(build_arbitration_request(role, value, barema, own, other, divergent))
            revised[role] = parse_judge_result(response, role)
        except JudgeOutputError as exc:
            notes.append(f"{role.value}: reconsideração inválida ({exc}); mantida a avaliação original.")

    final_a = revised[JudgeRole.A] or judge_a
    final_b = revised[JudgeRole.B] or judge_b
    still_divergent = [
        criterion
        for criterion in divergent
        if final_a.score_for(criterion) != final_b.score_for(criterion)
    ]
    resolved = not still_divergent and final_a.verdict is final_b.verdict

    return ArbitrationResult(
        arbitrated_criteria=divergent,
        judge_a_revised=revised[JudgeRole.A],
        judge_b_revised=revised[JudgeRole.B],
        resolved=resolved,
        note=" ".join(notes) or (
            "Divergência resolvida na única rodada permitida."
            if resolved
            else "Divergência persistiu após a rodada; encaminhado para revisão humana."
        ),
    )

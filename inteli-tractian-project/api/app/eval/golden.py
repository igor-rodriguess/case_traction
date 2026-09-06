"""Fronteira do Golden Set: entra no Eval, nunca no runtime dos agentes.

O loader existe para tornar a regra verificável em vez de disciplinar. Ele é o
único ponto do código autorizado a abrir `eval/expected-paths.json`, e
`assert_no_golden_in_runtime` prova, sobre um artefato de execução, que nada
daquela referência atravessou para o lado dos agentes.

Comparação de caminho é **conceitual**: cobertura e ordem aproximada, nunca
igualdade textual.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.eval.contracts import EvaluationInput, EvaluationReference, ExpectedStep


GOLDEN_PATH = Path(__file__).resolve().parents[3] / "eval" / "expected-paths.json"

_AGENT_FACING_FIELDS = (
    "understanding_output",
    "planner_output",
    "reporter_output",
)


class GoldenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathAlignment(GoldenModel):
    """Alinhamento entre o caminho esperado e o efetivamente percorrido."""

    expected_steps: int = Field(ge=0)
    observed_steps: int = Field(ge=0)
    matched_steps: tuple[str, ...] = ()
    missing_steps: tuple[str, ...] = ()
    extra_steps: tuple[str, ...] = ()
    tool_path_precision: float | None = None
    tool_path_recall: float | None = None
    required_tool_coverage: float | None = None
    forbidden_tool_rate: float = 0.0
    terminal_state_match: bool | None = None
    critical_step_coverage: float | None = None


class GoldenAccessError(PermissionError):
    """Tentativa de usar a referência fora da camada de avaliação."""


def load_reference(case_id: str, *, path: Path | None = None) -> EvaluationReference | None:
    """Carrega uma referência por id. Retorna `None` quando não existe."""

    source = path or GOLDEN_PATH
    if not source.exists():
        return None
    for item in json.loads(source.read_text(encoding="utf-8")):
        if item.get("id") == case_id or item.get("ticket_id") == case_id:
            return EvaluationReference(
                reference_id=item["id"],
                ticket_id=item.get("ticket_id"),
                root_question=item.get("root_question"),
                mode=item.get("mode"),
                expected_path=tuple(ExpectedStep.model_validate(step) for step in item.get("expected_path", [])),
                source=source.name,
            )
    return None


def available_reference_ids(*, path: Path | None = None) -> tuple[str, ...]:
    source = path or GOLDEN_PATH
    if not source.exists():
        return ()
    return tuple(item["id"] for item in json.loads(source.read_text(encoding="utf-8")))


def assert_no_golden_in_runtime(value: EvaluationInput) -> None:
    """Prova que a referência não contaminou as saídas dos agentes.

    O Eval pode conhecer o Golden; o Understanding, o Planner e o Reporter não.
    Se um identificador da referência aparecer no que um agente produziu, isso é
    vazamento e a avaliação inteira perde sentido.
    """

    reference = value.reference
    if reference is None:
        return
    markers = {reference.reference_id}
    if reference.ticket_id:
        markers.add(reference.ticket_id)
    for field in _AGENT_FACING_FIELDS:
        payload = getattr(value, field)
        if not payload:
            continue
        blob = json.dumps(payload, ensure_ascii=False)
        leaked = {marker for marker in markers if marker in blob}
        if leaked:
            raise GoldenAccessError(
                f"Referência do Golden encontrada em {field}: {sorted(leaked)}."
            )


def _normalise(path: str) -> str:
    return path.split("?", 1)[0].rstrip("/").lower()


def align_path(value: EvaluationInput) -> PathAlignment:
    """Compara caminho esperado e observado por cobertura, não por igualdade."""

    reference = value.reference
    observed = tuple(f"{item.method.upper()} {_normalise(item.path)}" for item in value.evidence_records)
    if reference is None:
        return PathAlignment(expected_steps=0, observed_steps=len(observed), extra_steps=observed)

    expected = tuple(f"{step.method} {_normalise(step.path)}" for step in reference.expected_path)
    # Passos de ACTION do Golden nunca são executáveis por este sistema: a
    # arquitetura os substitui por escalada segura, entao eles nao contam como
    # tool obrigatoria nem como caminho faltante.
    read_expected = tuple(step for step in expected if step.startswith("GET "))
    action_expected = tuple(step for step in expected if not step.startswith("GET "))

    matched = tuple(step for step in read_expected if step in observed)
    missing = tuple(step for step in read_expected if step not in observed)
    extra = tuple(step for step in observed if step not in read_expected)

    precision = round(len(matched) / len(observed), 4) if observed else None
    recall = round(len(matched) / len(read_expected), 4) if read_expected else None
    forbidden = sum(1 for step in observed if not step.startswith("GET "))

    terminal_match: bool | None = None
    if reference.mode:
        expected_terminal = {
            "inconclusive": {"SAFE_ESCALATION", "AWAITING_REQUIRED_INFORMATION"},
            "conflict": {"SAFE_ESCALATION"},
            "unavailable": {"SAFE_ESCALATION", "AWAITING_REQUIRED_INFORMATION"},
            "complete": {"GROUNDED_COMPLETION"},
            "partial": {"GROUNDED_COMPLETION", "SAFE_ESCALATION"},
        }.get(reference.mode.lower())
        if expected_terminal is not None:
            terminal_match = value.terminal_state in expected_terminal

    return PathAlignment(
        expected_steps=len(expected),
        observed_steps=len(observed),
        matched_steps=matched,
        missing_steps=missing,
        extra_steps=extra,
        tool_path_precision=precision,
        tool_path_recall=recall,
        required_tool_coverage=recall,
        forbidden_tool_rate=round(forbidden / len(observed), 4) if observed else 0.0,
        terminal_state_match=terminal_match,
        critical_step_coverage=(
            round(len(matched) / len(read_expected), 4) if read_expected else None
        ),
    )

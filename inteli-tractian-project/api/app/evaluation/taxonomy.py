"""Taxonomia fechada de terminalidade, erro e camada responsável.

A avaliação só é acionável se cada falha disser *onde* consertar. `PrimaryLayer`
separa problema de dados de problema de prompt, modelo, contrato, orquestração,
tool, API, grounding, Reporter ou provider — nenhuma dessas conclusões é
inferida por LLM.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TerminalStatus(str, Enum):
    """Terminalidades observáveis; só as três primeiras são consideradas válidas."""

    GROUNDED_COMPLETION = "GROUNDED_COMPLETION"
    SAFE_ESCALATION = "SAFE_ESCALATION"
    AWAITING_REQUIRED_INFORMATION = "AWAITING_REQUIRED_INFORMATION"
    FAILED = "FAILED"


VALID_TERMINAL_STATUSES: frozenset[TerminalStatus] = frozenset(
    {
        TerminalStatus.GROUNDED_COMPLETION,
        TerminalStatus.SAFE_ESCALATION,
        TerminalStatus.AWAITING_REQUIRED_INFORMATION,
    }
)


class FailureCategory(str, Enum):
    """Detalhamento obrigatório quando a terminalidade é FAILED."""

    DEAD_END = "DEAD_END"
    SILENT_TERMINATION = "SILENT_TERMINATION"
    INVALID_STATE = "INVALID_STATE"
    UNCLASSIFIED_ERROR = "UNCLASSIFIED_ERROR"


class EvaluationErrorCode(str, Enum):
    UNDERSTANDING_ERROR = "UNDERSTANDING_ERROR"
    PLANNER_ERROR = "PLANNER_ERROR"
    INVESTIGATOR_VALIDATION_ERROR = "INVESTIGATOR_VALIDATION_ERROR"
    INVESTIGATOR_DECISION_ERROR = "INVESTIGATOR_DECISION_ERROR"
    INVALID_TOOL = "INVALID_TOOL"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    LOOP = "LOOP"
    LIMIT_REACHED = "LIMIT_REACHED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DATA_COVERAGE_GAP = "DATA_COVERAGE_GAP"
    INVALID_CONCLUSION = "INVALID_CONCLUSION"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    REPORTER_ERROR = "REPORTER_ERROR"
    STATE_TRANSITION_ERROR = "STATE_TRANSITION_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class PrimaryLayer(str, Enum):
    DATA = "DATA"
    PROMPT = "PROMPT"
    MODEL = "MODEL"
    CONTRACT = "CONTRACT"
    ORCHESTRATION = "ORCHESTRATION"
    TOOL = "TOOL"
    API = "API"
    GROUNDING = "GROUNDING"
    REPORTER = "REPORTER"
    PROVIDER = "PROVIDER"
    OTHER = "OTHER"


DEFAULT_PRIMARY_LAYER: dict[EvaluationErrorCode, PrimaryLayer] = {
    EvaluationErrorCode.UNDERSTANDING_ERROR: PrimaryLayer.PROMPT,
    EvaluationErrorCode.PLANNER_ERROR: PrimaryLayer.PROMPT,
    EvaluationErrorCode.INVESTIGATOR_VALIDATION_ERROR: PrimaryLayer.CONTRACT,
    EvaluationErrorCode.INVESTIGATOR_DECISION_ERROR: PrimaryLayer.PROMPT,
    EvaluationErrorCode.INVALID_TOOL: PrimaryLayer.TOOL,
    EvaluationErrorCode.INVALID_ARGUMENT: PrimaryLayer.TOOL,
    EvaluationErrorCode.TOOL_EXECUTION_ERROR: PrimaryLayer.API,
    EvaluationErrorCode.PROVIDER_ERROR: PrimaryLayer.PROVIDER,
    EvaluationErrorCode.RATE_LIMIT: PrimaryLayer.PROVIDER,
    EvaluationErrorCode.TIMEOUT: PrimaryLayer.PROVIDER,
    EvaluationErrorCode.LOOP: PrimaryLayer.ORCHESTRATION,
    EvaluationErrorCode.LIMIT_REACHED: PrimaryLayer.ORCHESTRATION,
    EvaluationErrorCode.INSUFFICIENT_EVIDENCE: PrimaryLayer.DATA,
    EvaluationErrorCode.DATA_COVERAGE_GAP: PrimaryLayer.DATA,
    EvaluationErrorCode.INVALID_CONCLUSION: PrimaryLayer.GROUNDING,
    EvaluationErrorCode.UNSUPPORTED_CLAIM: PrimaryLayer.GROUNDING,
    EvaluationErrorCode.REPORTER_ERROR: PrimaryLayer.REPORTER,
    EvaluationErrorCode.STATE_TRANSITION_ERROR: PrimaryLayer.ORCHESTRATION,
    EvaluationErrorCode.SYSTEM_ERROR: PrimaryLayer.OTHER,
}


class EvaluationError(BaseModel):
    """Erro persistível; subcategoria preserva o diagnóstico já implementado."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: EvaluationErrorCode
    subcategory: str | None = Field(default=None, max_length=120)
    primary_layer: PrimaryLayer
    detail_sanitized: str = Field(max_length=500)

    @classmethod
    def of(
        cls,
        code: EvaluationErrorCode,
        *,
        subcategory: str | None = None,
        detail: str = "",
        primary_layer: PrimaryLayer | None = None,
    ) -> "EvaluationError":
        return cls(
            code=code,
            subcategory=subcategory,
            primary_layer=primary_layer or DEFAULT_PRIMARY_LAYER[code],
            detail_sanitized=detail[:500],
        )


class QualityVerdict(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class TrainingAssessment(str, Enum):
    NO_TRAINING_NEEDED = "NO_TRAINING_NEEDED"
    PROMPT_CALIBRATION_FIRST = "PROMPT_CALIBRATION_FIRST"
    TRAINING_CANDIDATE = "TRAINING_CANDIDATE"
    DATA_PROBLEM_FIRST = "DATA_PROBLEM_FIRST"
    INSUFFICIENT_EVIDENCE_TO_DECIDE = "INSUFFICIENT_EVIDENCE_TO_DECIDE"


class RunStatus(str, Enum):
    """Status final da rodada, incluindo pausa limpa por quota."""

    COMPLETED = "COMPLETED"
    RUN_PAUSED_PROVIDER_QUOTA = "RUN_PAUSED_PROVIDER_QUOTA"

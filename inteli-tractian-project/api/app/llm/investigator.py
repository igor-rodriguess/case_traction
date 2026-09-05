"""Fronteira auditável entre ``LLMResponse`` e ``InvestigationDecision``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.investigation import InvestigationDecision, InvestigationDecisionType, InvestigationState
from app.llm.contracts import LLMRequest, LLMResponse, LLMResponseStatus
from app.llm.provider import LLMProvider
from app.tools import get_investigator_tools


class InvestigatorValidationStage(str, Enum):
    PROVIDER_OUTPUT = "provider_output"
    CANONICALIZATION = "canonicalization"
    JSON_EXTRACTION = "json_extraction"
    SCHEMA_VALIDATION = "schema_validation"
    DOMAIN_INVARIANTS = "domain_invariants"
    TOOL_VALIDATION = "tool_validation"
    COMPLETION_POLICY = "completion_policy"


class InvestigatorValidationCategory(str, Enum):
    MALFORMED_JSON = "MALFORMED_JSON"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    EXTRA_FIELD = "EXTRA_FIELD"
    INVALID_ENUM = "INVALID_ENUM"
    INVALID_FIELD_TYPE = "INVALID_FIELD_TYPE"
    TOOL_CALL_WITHOUT_TOOL_REQUEST = "TOOL_CALL_WITHOUT_TOOL_REQUEST"
    NON_TOOL_DECISION_WITH_TOOL_REQUEST = "NON_TOOL_DECISION_WITH_TOOL_REQUEST"
    INVALID_TOOL_NAME = "INVALID_TOOL_NAME"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    ASK_USER_WITHOUT_REQUIRED_INFORMATION = "ASK_USER_WITHOUT_REQUIRED_INFORMATION"
    ANSWER_WITHOUT_SUPPORTING_EVIDENCE = "ANSWER_WITHOUT_SUPPORTING_EVIDENCE"
    INVALID_EVIDENCE_REFERENCE = "INVALID_EVIDENCE_REFERENCE"
    FORBIDDEN_ACTION = "FORBIDDEN_ACTION"
    EMPTY_REASON_CODES_WHEN_REQUIRED = "EMPTY_REASON_CODES_WHEN_REQUIRED"
    NULL_NOT_ALLOWED = "NULL_NOT_ALLOWED"
    STRUCTURED_OUTPUT_MISMATCH = "STRUCTURED_OUTPUT_MISMATCH"
    ADAPTER_NORMALIZATION_ERROR = "ADAPTER_NORMALIZATION_ERROR"
    OTHER_CONTRACT_VIOLATION = "OTHER_CONTRACT_VIOLATION"


class InvestigatorRecoveryAction(str, Enum):
    ACCEPT = "ACCEPT"
    DETERMINISTIC_NORMALIZATION = "DETERMINISTIC_NORMALIZATION"
    ONE_LLM_REPAIR = "ONE_LLM_REPAIR"
    FAIL_SAFE = "FAIL_SAFE"


class InvestigatorValidationResult(BaseModel):
    """Diagnóstico persistível; nunca contém segredo nem raciocínio interno."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    stage: InvestigatorValidationStage
    category: InvestigatorValidationCategory | None = None
    field: str | None = None
    message_sanitized: str = Field(min_length=1, max_length=500)
    raw_output_reference: str | None = None
    recoverable: bool = False
    retryable: bool = False
    provider: str
    model: str
    prompt_version: str
    normalization_applied: str | None = None


class LLMOutputValidationError(ValueError):
    """Saída bloqueada com causa contratual estruturada e sanitizada."""

    def __init__(self, result: InvestigatorValidationResult | str, *, parsed_output: object = None) -> None:
        if isinstance(result, str):
            super().__init__(result)
            self.result: InvestigatorValidationResult | None = None
        else:
            super().__init__(f"{result.stage.value}:{result.category.value if result.category else 'UNKNOWN'}: {result.message_sanitized}")
            self.result = result
        self.parsed_output = parsed_output


def _output_reference(output: object) -> str:
    serialized = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _result(
    response: LLMResponse,
    *,
    valid: bool,
    stage: InvestigatorValidationStage,
    category: InvestigatorValidationCategory | None,
    message: str,
    field: str | None = None,
    recoverable: bool = False,
    retryable: bool = False,
    normalization: str | None = None,
) -> InvestigatorValidationResult:
    return InvestigatorValidationResult(
        valid=valid,
        stage=stage,
        category=category,
        field=field,
        message_sanitized=message,
        raw_output_reference=_output_reference(response.output) if response.output is not None else None,
        recoverable=recoverable,
        retryable=retryable,
        provider=response.provider,
        model=response.model,
        prompt_version=response.metadata.prompt_version,
        normalization_applied=normalization,
    )


def _classify_validation_error(exc: ValidationError, payload: dict[str, Any]) -> tuple[InvestigatorValidationStage, InvestigatorValidationCategory, str | None, str]:
    error = exc.errors(include_url=False, include_context=False)[0]
    field = ".".join(str(item) for item in error.get("loc", ())) or None
    error_type = str(error.get("type", ""))
    message = str(error.get("msg", "Contrato inválido."))
    decision_type = payload.get("type")

    if decision_type == "action":
        return InvestigatorValidationStage.DOMAIN_INVARIANTS, InvestigatorValidationCategory.FORBIDDEN_ACTION, "type", "ACTION não pertence ao contrato do Investigator."
    if "TOOL_CALL exige tool_request" in message:
        return InvestigatorValidationStage.DOMAIN_INVARIANTS, InvestigatorValidationCategory.TOOL_CALL_WITHOUT_TOOL_REQUEST, "tool_request", message
    if "tool_request só é permitido" in message:
        return InvestigatorValidationStage.DOMAIN_INVARIANTS, InvestigatorValidationCategory.NON_TOOL_DECISION_WITH_TOOL_REQUEST, "tool_request", message
    if "ASK_USER exige required_information" in message:
        return InvestigatorValidationStage.DOMAIN_INVARIANTS, InvestigatorValidationCategory.ASK_USER_WITHOUT_REQUIRED_INFORMATION, "required_information", message
    if "READ tool autorizada" in message:
        return InvestigatorValidationStage.DOMAIN_INVARIANTS, InvestigatorValidationCategory.INVALID_TOOL_NAME, "tool_request.tool_name", message
    if field == "reason_codes" and error_type in {"too_short", "missing"}:
        return InvestigatorValidationStage.SCHEMA_VALIDATION, InvestigatorValidationCategory.EMPTY_REASON_CODES_WHEN_REQUIRED, field, message
    if error_type == "extra_forbidden":
        return InvestigatorValidationStage.SCHEMA_VALIDATION, InvestigatorValidationCategory.EXTRA_FIELD, field, message
    if error_type == "missing":
        return InvestigatorValidationStage.SCHEMA_VALIDATION, InvestigatorValidationCategory.MISSING_REQUIRED_FIELD, field, message
    if error_type == "enum":
        return InvestigatorValidationStage.SCHEMA_VALIDATION, InvestigatorValidationCategory.INVALID_ENUM, field, message
    if error.get("input") is None:
        return InvestigatorValidationStage.SCHEMA_VALIDATION, InvestigatorValidationCategory.NULL_NOT_ALLOWED, field, message
    if error_type.endswith("_type") or "parsing" in error_type:
        return InvestigatorValidationStage.SCHEMA_VALIDATION, InvestigatorValidationCategory.INVALID_FIELD_TYPE, field, message
    return InvestigatorValidationStage.DOMAIN_INVARIANTS, InvestigatorValidationCategory.OTHER_CONTRACT_VIOLATION, field, message


def validate_investigation_decision(response: LLMResponse) -> tuple[InvestigatorValidationResult, InvestigationDecision | None, dict[str, Any] | None]:
    """Valida por camada e devolve diagnóstico, decisão e JSON parseado."""

    if response.status is not LLMResponseStatus.SUCCESS:
        result = _result(response, valid=False, stage=InvestigatorValidationStage.PROVIDER_OUTPUT, category=InvestigatorValidationCategory.STRUCTURED_OUTPUT_MISMATCH, message=f"Provider retornou status não executável: {response.status.value}.", retryable=bool(response.error and response.error.retryable))
        return result, None, None

    output: object = response.output
    normalization = None
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            result = _result(response, valid=False, stage=InvestigatorValidationStage.JSON_EXTRACTION, category=InvestigatorValidationCategory.MALFORMED_JSON, message="Provider retornou JSON inválido.", recoverable=True, retryable=True)
            return result, None, None
        if isinstance(output, str):
            try:
                decoded = json.loads(output)
            except json.JSONDecodeError:
                result = _result(response, valid=False, stage=InvestigatorValidationStage.CANONICALIZATION, category=InvestigatorValidationCategory.ADAPTER_NORMALIZATION_ERROR, message="JSON externo continha texto não estruturado.", recoverable=True, retryable=True)
                return result, None, None
            output = decoded
            normalization = "DOUBLE_ENCODED_JSON_DECODE"

    if not isinstance(output, dict):
        result = _result(response, valid=False, stage=InvestigatorValidationStage.JSON_EXTRACTION, category=InvestigatorValidationCategory.STRUCTURED_OUTPUT_MISMATCH, message="Provider deve retornar um objeto de decisão JSON.", recoverable=True, retryable=True)
        return result, None, None

    try:
        decision = InvestigationDecision.model_validate(output)
    except ValidationError as exc:
        stage, category, field, message = _classify_validation_error(exc, output)
        result = _result(response, valid=False, stage=stage, category=category, field=field, message=message, recoverable=True, retryable=True, normalization=normalization)
        return result, None, output

    if decision.type is InvestigationDecisionType.TOOL_CALL:
        request = decision.tool_request
        assert request is not None
        tool = next((item for item in get_investigator_tools() if item.name == request.tool_name), None)
        if tool is None:
            result = _result(response, valid=False, stage=InvestigatorValidationStage.TOOL_VALIDATION, category=InvestigatorValidationCategory.INVALID_TOOL_NAME, field="tool_request.tool_name", message="Tool solicitada não é autorizada ao Investigator.")
            return result, None, output
        try:
            tool.input_schema.model_validate(request.arguments)
        except ValidationError as exc:
            field = ".".join(str(item) for item in exc.errors(include_url=False)[0].get("loc", ())) or "tool_request.arguments"
            result = _result(response, valid=False, stage=InvestigatorValidationStage.TOOL_VALIDATION, category=InvestigatorValidationCategory.INVALID_TOOL_ARGUMENTS, field=field, message="Argumentos da tool violam seu schema aprovado.", recoverable=True, retryable=True)
            return result, None, output

    result = _result(response, valid=True, stage=InvestigatorValidationStage.DOMAIN_INVARIANTS, category=None, message="InvestigationDecision válida.", normalization=normalization)
    return result, decision, output


def parse_investigation_decision(response: LLMResponse) -> InvestigationDecision:
    """Compatibilidade: levanta erro rico quando a validação por camadas falha."""

    result, decision, parsed = validate_investigation_decision(response)
    if not result.valid or decision is None:
        raise LLMOutputValidationError(result, parsed_output=parsed)
    return decision


def recovery_action(result: InvestigatorValidationResult) -> InvestigatorRecoveryAction:
    """Política fechada: no máximo um repair e nunca repair de ACTION."""

    if result.valid:
        return InvestigatorRecoveryAction.DETERMINISTIC_NORMALIZATION if result.normalization_applied else InvestigatorRecoveryAction.ACCEPT
    if result.category is InvestigatorValidationCategory.FORBIDDEN_ACTION:
        return InvestigatorRecoveryAction.FAIL_SAFE
    if result.recoverable and result.retryable:
        return InvestigatorRecoveryAction.ONE_LLM_REPAIR
    return InvestigatorRecoveryAction.FAIL_SAFE


RequestFactory = Callable[[InvestigationState], LLMRequest]


class LLMInvestigatorBoundary:
    """Adapter injetável para usar LLMProvider na porta já consumida pelo grafo."""

    def __init__(self, provider: LLMProvider, request_factory: RequestFactory) -> None:
        self._provider = provider
        self._request_factory = request_factory
        self.responses: list[LLMResponse] = []

    def __call__(self, state: InvestigationState) -> InvestigationDecision:
        request = self._request_factory(state)
        if request.request_id != state.request_id:
            result = InvestigatorValidationResult(valid=False, stage=InvestigatorValidationStage.CANONICALIZATION, category=InvestigatorValidationCategory.ADAPTER_NORMALIZATION_ERROR, field="request_id", message_sanitized="LLMRequest deve preservar o request_id do caso.", provider="boundary", model="unknown", prompt_version=request.prompt_version)
            raise LLMOutputValidationError(result)
        response = self._provider.infer(request)
        self.responses.append(response)
        return parse_investigation_decision(response)

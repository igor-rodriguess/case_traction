"""Matriz offline da fronteira contratual do Investigator; nunca chama rede ou tool."""

from __future__ import annotations

import json

import pytest

from app.llm import LLMMetadata, LLMResponse, LLMResponseStatus
from app.llm.investigator import (
    InvestigatorValidationCategory as Category,
    InvestigatorRecoveryAction,
    InvestigatorValidationStage as Stage,
    LLMOutputValidationError,
    parse_investigation_decision,
    recovery_action,
    validate_investigation_decision,
)


def _response(output: object) -> LLMResponse:
    return LLMResponse(
        request_id="validation_test",
        provider="gemini",
        model="gemini-test",
        status=LLMResponseStatus.SUCCESS,
        output=output,
        duration_ms=1,
        metadata=LLMMetadata(prompt_version="e2e_investigator_v4"),
    )


def _payload(kind: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "decision_id": "decision_test",
        "type": kind,
        "reason_codes": ["TEST"],
        "tool_request": None,
        "required_information": [],
        "supporting_evidence_ids": [],
    }
    value.update(changes)
    return value


@pytest.mark.parametrize(
    "payload",
    [
        _payload("continue"),
        _payload("tool_call", tool_request={"tool_name": "get_asset_context", "arguments": {"asset_id": "asset_B211"}}),
        _payload("ask_user", required_information=["asset_id"]),
        _payload("answer", supporting_evidence_ids=["evidence_001"]),
        _payload("escalate"),
    ],
)
def test_valid_decision_matrix(payload) -> None:
    result, decision, parsed = validate_investigation_decision(_response(json.dumps(payload)))
    assert result.valid and result.category is None
    assert decision is not None and parsed == payload


@pytest.mark.parametrize(
    "payload, category, stage",
    [
        (_payload("tool_call"), Category.TOOL_CALL_WITHOUT_TOOL_REQUEST, Stage.DOMAIN_INVARIANTS),
        (_payload("tool_call", tool_request={"tool_name": "patch_asset", "arguments": {}}), Category.INVALID_TOOL_NAME, Stage.DOMAIN_INVARIANTS),
        (_payload("ask_user"), Category.ASK_USER_WITHOUT_REQUIRED_INFORMATION, Stage.DOMAIN_INVARIANTS),
        (_payload("answer", tool_request={"tool_name": "get_asset_context", "arguments": {"asset_id": "asset_B211"}}), Category.NON_TOOL_DECISION_WITH_TOOL_REQUEST, Stage.DOMAIN_INVARIANTS),
        (_payload("invalid"), Category.INVALID_ENUM, Stage.SCHEMA_VALIDATION),
        ({**_payload("continue"), "unexpected": True}, Category.EXTRA_FIELD, Stage.SCHEMA_VALIDATION),
        (_payload("continue", decision_id=None), Category.NULL_NOT_ALLOWED, Stage.SCHEMA_VALIDATION),
        (_payload("continue", reason_codes=[]), Category.EMPTY_REASON_CODES_WHEN_REQUIRED, Stage.SCHEMA_VALIDATION),
        (_payload("action"), Category.FORBIDDEN_ACTION, Stage.DOMAIN_INVARIANTS),
        (_payload("tool_call", tool_request={"tool_name": "get_asset_context", "arguments": {}}), Category.INVALID_TOOL_ARGUMENTS, Stage.TOOL_VALIDATION),
    ],
)
def test_invalid_decision_matrix_is_classified_and_never_returns_executable_decision(payload, category, stage) -> None:
    result, decision, _ = validate_investigation_decision(_response(payload))
    assert not result.valid and result.category is category and result.stage is stage
    assert decision is None


def test_malformed_json_is_classified() -> None:
    result, decision, parsed = validate_investigation_decision(_response("{not-json"))
    assert (result.stage, result.category) == (Stage.JSON_EXTRACTION, Category.MALFORMED_JSON)
    assert decision is None and parsed is None and result.recoverable


def test_double_encoded_json_has_only_deterministic_normalization() -> None:
    payload = _payload("continue")
    result, decision, parsed = validate_investigation_decision(_response(json.dumps(json.dumps(payload))))
    assert result.valid and result.normalization_applied == "DOUBLE_ENCODED_JSON_DECODE"
    assert decision is not None and parsed == payload


def test_high_level_exception_preserves_structured_cause() -> None:
    with pytest.raises(LLMOutputValidationError) as caught:
        parse_investigation_decision(_response(_payload("invalid")))
    assert caught.value.result.category is Category.INVALID_ENUM
    assert caught.value.result.field == "type"


def test_recovery_policy_allows_one_repair_but_never_repairs_action() -> None:
    malformed, *_ = validate_investigation_decision(_response("{not-json"))
    action, *_ = validate_investigation_decision(_response(_payload("action")))
    assert recovery_action(malformed) is InvestigatorRecoveryAction.ONE_LLM_REPAIR
    assert recovery_action(action) is InvestigatorRecoveryAction.FAIL_SAFE

"""Gera showcase sintético da Provider Layer, sem Golden Set, rede ou API key."""

from __future__ import annotations

import json
from pathlib import Path

from app.llm import (
    FakeLLMProvider,
    LLMGenerationParameters,
    LLMMessage,
    LLMMetadata,
    LLMOutputValidationError,
    LLMRequest,
    LLMResponse,
    LLMResponseStatus,
    LLMUsage,
    parse_investigation_decision,
)


EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "architecture" / "examples" / "07-llm-provider-example.json"
)


def example_request() -> LLMRequest:
    return LLMRequest(
        request_id="request_fixture_07",
        agent_role="investigator",
        messages=(
            LLMMessage(role="system", content="Retorne somente uma decisão JSON compatível com o schema aprovado."),
            LLMMessage(role="user", content="Investigue o aumento de RMS do asset_B211."),
        ),
        prompt_version="investigator.v1",
        generation=LLMGenerationParameters(temperature=0),
        expected_schema={"type": "object", "title": "InvestigationDecision"},
        max_output_tokens=400,
        timeout_seconds=10,
    )


def fixture_response(output: object) -> LLMResponse:
    return LLMResponse(
        request_id="request_fixture_07",
        response_id="response_fixture_07",
        provider="fake",
        model="fixture-model",
        status=LLMResponseStatus.SUCCESS,
        output=output,
        usage=LLMUsage(input_tokens=24, output_tokens=18, total_tokens=42),
        duration_ms=3.0,
        metadata=LLMMetadata(prompt_version="investigator.v1", finish_reason="stop"),
    )


def build_showcase() -> dict[str, object]:
    valid_output = {
        "decision_id": "decision_fixture_07",
        "type": "tool_call",
        "reason_codes": ["NEED_VIBRATION_DATA"],
        "tool_request": {"tool_name": "get_asset_rms", "arguments": {"asset_id": "asset_B211"}},
    }
    request = example_request()
    valid_response = FakeLLMProvider([fixture_response(valid_output)]).infer(request)
    decision = parse_investigation_decision(valid_response)
    invalid_response = fixture_response(
        {
            "decision_id": "decision_invalid_07",
            "type": "tool_call",
            "reason_codes": ["UNSAFE_REQUEST"],
            "tool_request": {"tool_name": "request_case_escalation", "arguments": {"case_id": "case_1"}},
        }
    )
    try:
        parse_investigation_decision(invalid_response)
    except LLMOutputValidationError as exc:
        rejection = {"accepted": False, "error_type": type(exc).__name__, "message": str(exc)}
    else:  # pragma: no cover - protege o gerador se a boundary for enfraquecida.
        raise AssertionError("O showcase exige que ACTION seja rejeitada.")
    return {
        "showcase_type": "deterministic_llm_provider_layer",
        "external_calls": 0,
        "tokens_consumed_by_real_provider": 0,
        "valid_flow": {
            "llm_request": request.model_dump(mode="json"),
            "llm_response": valid_response.model_dump(mode="json"),
            "investigation_decision": decision.model_dump(mode="json"),
            "tool_request": decision.tool_request.model_dump(mode="json") if decision.tool_request else None,
        },
        "invalid_action_response_rejected": {
            "llm_response": invalid_response.model_dump(mode="json"),
            "rejection": rejection,
        },
    }


def write_showcase(path: Path = EXAMPLE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_showcase(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_showcase())

"""Smoke real, pequeno e sem tools do contrato Investigator V4."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from app.intelligence import CapabilityReference, EvidenceSummary, InvestigatorInput, TraceSummary
from app.investigation import InvestigationDecision, InvestigationDecisionType
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, StructuredOutputMode
from app.llm.investigator import InvestigatorRecoveryAction, recovery_action, validate_investigation_decision
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from scripts.diagnose_llm_providers import load_local_env
from scripts.generate_investigation_state_example import example_understanding
from scripts.smoke_llm_contracts import fixture_plan


ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "docs" / "architecture" / "examples" / "09-4d-contract-smoke.json"
PROMPT_VERSION = "e2e_investigator_v4"
SYSTEM_PROMPT = """Return only one JSON object matching InvestigationDecision exactly.
Allowed type values: continue, tool_call, ask_user, answer, escalate. Never emit ACTION.
Always include decision_id, type, non-empty reason_codes, tool_request, required_information, supporting_evidence_ids.
For tool_call, tool_request must contain one permitted READ tool name and schema-valid arguments; otherwise tool_request must be null.
For ask_user, required_information must be non-empty; otherwise required_information must be empty.
For answer, cite only evidence IDs present in the input. Do not add fields."""


def contract_cases() -> tuple[tuple[str, InvestigationDecisionType, InvestigatorInput], ...]:
    common = dict(
        understanding=example_understanding(), plan=fixture_plan(), phase="investigating",
        permitted_capabilities=(CapabilityReference(name="get_asset_context"), CapabilityReference(name="get_asset_rms")),
        max_investigation_steps=4, max_tool_calls=2,
    )
    empty = dict(evidence=EvidenceSummary(), trace=TraceSummary(trace_id="trace_contract", tool_call_count=0))
    complete = dict(
        evidence=EvidenceSummary(evidence_ids=("evidence_complete_001",), statuses=("complete",), relevant_results=({"evidence_id": "evidence_complete_001", "asset_id": "asset_B211"},)),
        trace=TraceSummary(trace_id="trace_contract", tool_call_count=1, last_tool_name="get_asset_context", last_call_id="call_001"),
    )
    unavailable = dict(
        evidence=EvidenceSummary(evidence_ids=("evidence_unavailable_001",), statuses=("unavailable",), relevant_results=({"evidence_id": "evidence_unavailable_001"},)),
        trace=TraceSummary(trace_id="trace_contract", tool_call_count=2, last_tool_name="get_asset_rms", last_call_id="call_002"),
    )
    return (
        ("TOOL_CALL", InvestigationDecisionType.TOOL_CALL, InvestigatorInput(**common, **empty, investigation_step_count=0, tool_call_count=0)),
        ("ASK_USER", InvestigationDecisionType.ASK_USER, InvestigatorInput(**common, **empty, investigation_step_count=1, tool_call_count=0)),
        ("ANSWER", InvestigationDecisionType.ANSWER, InvestigatorInput(**common, **complete, investigation_step_count=2, tool_call_count=1)),
        ("ESCALATE", InvestigationDecisionType.ESCALATE, InvestigatorInput(**common, **unavailable, investigation_step_count=3, tool_call_count=2)),
        ("CONTINUE", InvestigationDecisionType.CONTINUE, InvestigatorInput(**common, **complete, investigation_step_count=1, tool_call_count=1)),
    )


def _request(name: str, value: InvestigatorInput, *, repair: dict[str, object] | None = None) -> LLMRequest:
    messages = [LLMMessage(role="system", content=SYSTEM_PROMPT)]
    if repair:
        messages.append(LLMMessage(role="user", content=json.dumps({
            "instruction": "Your previous output violated the contract. Return only a schema-valid replacement; do not infer an expected answer.",
            "validation_category": repair["category"], "invalid_field": repair["field"], "previous_output_sanitized": repair["output"],
        }, ensure_ascii=False)))
    messages.append(LLMMessage(role="user", content=f"CONTRACT_SCENARIO={name}\nReturn decision type {name.lower()} for this schema-only fixture.\n{json.dumps(value.model_dump(mode='json'), ensure_ascii=False)}"))
    return LLMRequest(
        request_id=f"contract_v4_{uuid4().hex}", agent_role="investigator", messages=tuple(messages),
        prompt_version=PROMPT_VERSION, generation=LLMGenerationParameters(temperature=0.0),
        expected_schema=InvestigationDecision.model_json_schema(), structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        max_output_tokens=700, timeout_seconds=45,
    )


def _record(provider, response, result, decision, attempt: int) -> dict[str, object]:
    return {
        "attempt_number": attempt,
        "provider_raw_output_sanitized": provider.last_raw_response_sanitized,
        "canonical_llm_response": response.model_dump(mode="json"),
        "parsed_json": decision.model_dump(mode="json") if decision else None,
        "validation": result.model_dump(mode="json"),
        "latency_ms": response.duration_ms,
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    load_local_env(ROOT / "api" / ".env")
    config = default_provider_configs()[ProviderName.GEMINI]
    if not args.execute:
        print(f"READY model={config.model} calls=5 max_repairs=5")
        return 0
    provider = create_provider(config)
    results: list[dict[str, object]] = []
    try:
        for name, expected, value in contract_cases():
            response = provider.infer(_request(name, value))
            validation, decision, parsed = validate_investigation_decision(response)
            attempts = [_record(provider, response, validation, decision, 1)]
            repaired = False
            if not validation.valid and recovery_action(validation) is InvestigatorRecoveryAction.ONE_LLM_REPAIR:
                repaired = True
                response = provider.infer(_request(name, value, repair={"category": validation.category.value if validation.category else None, "field": validation.field, "output": parsed if parsed is not None else response.output}))
                validation, decision, _ = validate_investigation_decision(response)
                attempts.append(_record(provider, response, validation, decision, 2))
            passed = bool(validation.valid and decision and decision.type is expected)
            results.append({"scenario": name, "expected": expected.value, "actual": decision.type.value if decision else None, "passed": passed, "first_pass_valid": attempts[0]["validation"]["valid"], "repair_attempted": repaired, "repair_successful": repaired and validation.valid, "attempts": attempts})
    finally:
        provider.close()
    total = len(results)
    artifact = {
        "prompt_version": PROMPT_VERSION, "provider": "gemini", "model": config.model,
        "initial_calls": total, "repair_calls": sum(bool(item["repair_attempted"]) for item in results),
        "first_pass_valid_rate": sum(bool(item["first_pass_valid"]) for item in results) / total,
        "repair_rate": sum(bool(item["repair_attempted"]) for item in results) / total,
        "failed_after_repair_rate": sum(bool(item["repair_attempted"]) and not bool(item["passed"]) for item in results) / total,
        "forbidden_action_rate": sum(item["actual"] == "action" for item in results) / total,
        "invalid_tool_rate": sum(any(attempt["validation"]["category"] in {"INVALID_TOOL_NAME", "INVALID_TOOL_ARGUMENTS"} for attempt in item["attempts"]) for item in results) / total,
        "adapter_errors": sum(any(attempt["validation"]["stage"] == "canonicalization" and not attempt["validation"]["valid"] for attempt in item["attempts"]) for item in results),
        "results": results,
    }
    RESULT_PATH.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: artifact[key] for key in ("first_pass_valid_rate", "repair_rate", "failed_after_repair_rate", "forbidden_action_rate", "invalid_tool_rate", "adapter_errors")}, ensure_ascii=False))
    return 0 if all(bool(item["passed"]) for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Dois smokes reais e sintéticos da Completion Policy V3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from app.intelligence import CapabilityReference, EvidenceSummary, InvestigatorInput, TraceSummary
from app.investigation import InvestigationDecision, InvestigationDecisionType
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, StructuredOutputMode
from app.llm.investigator import parse_investigation_decision
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from scripts.diagnose_llm_providers import load_local_env
from scripts.smoke_llm_contracts import fixture_plan
from scripts.generate_investigation_state_example import example_understanding


ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "docs" / "architecture" / "examples" / "09-4c-completion-smokes.json"
PROMPT = """Return only one valid InvestigationDecision JSON. Never call ACTIONs.
For SHOULD_ANSWER return ANSWER with supporting_evidence_ids containing evidence_complete_001.
For SHOULD_ESCALATE return ESCALATE because the evidence is unavailable and the tool budget is exhausted.
Do not include tool_request or required_information for ANSWER or ESCALATE."""


def cases() -> tuple[tuple[str, InvestigatorInput, InvestigationDecisionType], ...]:
    common = dict(
        understanding=example_understanding(), plan=fixture_plan(), phase="investigating",
        permitted_capabilities=(CapabilityReference(name="get_asset_rms"),),
        investigation_step_count=1, max_investigation_steps=3, max_tool_calls=1,
    )
    answer = InvestigatorInput(
        **common, tool_call_count=1,
        evidence=EvidenceSummary(evidence_ids=("evidence_complete_001",), statuses=("complete",), relevant_results=({"evidence_id": "evidence_complete_001", "asset_id": "asset_B211", "rms_trend": "elevated"},)),
        trace=TraceSummary(trace_id="trace_smoke_answer", tool_call_count=1, last_tool_name="get_asset_rms", last_call_id="call_001"),
    )
    escalate = InvestigatorInput(
        **common, tool_call_count=1,
        evidence=EvidenceSummary(evidence_ids=("evidence_unavailable_001",), statuses=("unavailable",), relevant_results=({"evidence_id": "evidence_unavailable_001", "asset_id": "asset_B211"},)),
        trace=TraceSummary(trace_id="trace_smoke_escalate", tool_call_count=1, last_tool_name="get_asset_rms", last_call_id="call_001"),
    )
    return (("SHOULD_ANSWER", answer, InvestigationDecisionType.ANSWER), ("SHOULD_ESCALATE", escalate, InvestigationDecisionType.ESCALATE))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    load_local_env(ROOT / "api" / ".env")
    config = default_provider_configs()[ProviderName.GEMINI]
    if not args.execute:
        print(f"READY model={config.model} cases={[name for name, *_ in cases()]}")
        return 0
    provider = create_provider(config)
    results = []
    try:
        for name, value, expected in cases():
            request = LLMRequest(
                request_id=f"completion_smoke_{uuid4().hex}", agent_role="investigator",
                messages=(LLMMessage(role="system", content=PROMPT), LLMMessage(role="user", content=f"SCENARIO={name}\n{json.dumps(value.model_dump(mode='json'), ensure_ascii=False)}")),
                prompt_version="e2e_investigator_v3", generation=LLMGenerationParameters(temperature=1.0),
                expected_schema=InvestigationDecision.model_json_schema(), structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
                max_output_tokens=500, timeout_seconds=45,
            )
            response = provider.infer(request)
            decision = parse_investigation_decision(response)
            passed = decision.type is expected and (name != "SHOULD_ANSWER" or decision.supporting_evidence_ids == ("evidence_complete_001",))
            results.append({"scenario": name, "expected": expected.value, "actual": decision.type.value, "passed": passed, "provider": response.provider, "model": response.model, "latency_ms": response.duration_ms, "usage": response.usage.model_dump(mode="json") if response.usage else None})
    finally:
        provider.close()
    RESULT_PATH.write_text(json.dumps({"external_calls": 2, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

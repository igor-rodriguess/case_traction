"""Smoke manual dos três contratos cognitivos com uma única chamada Groq cada."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.agents.understanding.prompts import SYSTEM_PROMPT, build_user_prompt
from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput
from app.intelligence.boundaries import parse_planner_output, parse_reporter_output
from app.intelligence.contracts import (
    CapabilityReference, Claim, EvidenceSummary, InvestigationConclusion, InvestigatorInput,
    PlannerInput, PlannerOutput, ReporterInput, ReporterOutput, TraceSummary,
)
from app.investigation import InvestigationDecision
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, StructuredOutputMode
from app.llm.investigator import parse_investigation_decision
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from scripts.diagnose_llm_providers import load_local_env
from scripts.generate_investigation_state_example import example_understanding


RESULT_PATH = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "examples" / "09-2-real-contract-smoke.json"
BENCHMARK_RESULT_PATH = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "examples" / "09-3-provider-comparison.json"
PROMPT_VERSION = "contract_smoke.v4"


def fixture_plan() -> PlannerOutput:
    return PlannerOutput.model_validate({
        "plan_id": "plan_contract_fixture", "objectives": ["Verificar se RMS diverge do baseline."],
        "investigation_questions": ["A tendência RMS está acima da referência?"],
        "suggested_capabilities": [{"name": "get_asset_rms"}], "dependencies": [], "missing_information": [],
        "stopping_conditions": ["Evidência suficiente ou limitação explícita."], "reason_codes": ["RMS_DEVIATION"],
    })


def fixture_understanding_input() -> UnderstandingInput:
    return UnderstandingInput.model_validate({
        "message": "Verifique se a tendência RMS do ativo asset_B211 precisa de investigação nesta semana.",
        "available_context": {
            "tenant_ref": "tenant_contract_fixture",
            "asset_refs": ["asset_B211"],
            "role": "maintenance_analyst",
            "permissions": ["read"],
        },
    })


def parse_understanding_output(response) -> UnderstandingOutput:
    if response.status.value != "success":
        raise ValueError("Provider não retornou uma resposta executável.")
    payload = json.loads(response.output) if isinstance(response.output, str) else response.output
    return UnderstandingOutput.model_validate(payload)


def fixture_conclusion() -> InvestigationConclusion:
    claim = Claim(claim_id="claim_contract_fixture", statement="A tendência RMS está elevada na evidência sintética.", supporting_evidence_ids=("evidence_contract_001",), limitation="Evidência sintética para validação de contrato.")
    return InvestigationConclusion(conclusion_id="conclusion_contract_fixture", claims=(claim,), supporting_evidence_ids=("evidence_contract_001",), limitations=("Não representa uma investigação real.",), unresolved_points=("Baseline real não foi consultado.",), reason_codes=("SYNTHETIC_CONTRACT_SMOKE",))


def fixture_inputs() -> tuple[PlannerInput, InvestigatorInput, ReporterInput]:
    understanding = example_understanding()
    capability = CapabilityReference(name="get_asset_rms")
    plan = fixture_plan()
    evidence = EvidenceSummary(evidence_ids=("evidence_contract_001",), statuses=("complete",), relevant_results=({"asset_id": "asset_B211", "rms_trend": "elevated", "source": "synthetic_fixture"},))
    trace = TraceSummary(trace_id="trace_contract_fixture", tool_call_count=0)
    planner = PlannerInput(understanding=understanding, permitted_context={"source": "synthetic_contract_smoke"}, available_capabilities=(capability,), max_investigation_steps=3, max_tool_calls=1)
    investigator = InvestigatorInput(understanding=understanding, plan=plan, phase="investigating", evidence=evidence, trace=trace, permitted_capabilities=(capability,), investigation_step_count=0, max_investigation_steps=3, tool_call_count=0, max_tool_calls=1)
    reporter = ReporterInput(case_id="case_contract_fixture", trace_id=trace.trace_id, understanding=understanding, plan=plan, conclusion=fixture_conclusion(), evidence=evidence, trace=trace)
    return planner, investigator, reporter


def request(component: str, value: object, schema: dict, instruction: str, max_output_tokens: int, mode: StructuredOutputMode = StructuredOutputMode.JSON_SCHEMA, temperature: float = 0, prompt_version: str | None = None) -> LLMRequest:
    return LLMRequest(
        request_id=f"contract_{component}_{uuid4().hex}", agent_role=component,
        messages=(
            LLMMessage(role="system", content="Return only a JSON object matching the supplied schema. Do not expose chain-of-thought. Never request or execute ACTIONs or tools."),
            LLMMessage(role="user", content=f"{instruction}\nINPUT:\n{json.dumps(value.model_dump(mode='json'), ensure_ascii=False)}"),
        ), prompt_version=prompt_version or f"{PROMPT_VERSION}.{component}", generation=LLMGenerationParameters(temperature=temperature), expected_schema=schema, structured_output_mode=mode,
        max_output_tokens=max_output_tokens, timeout_seconds=45,
    )


def case_definitions(provider_name: ProviderName = ProviderName.GROQ) -> list[tuple[str, object, LLMRequest, object]]:
    planner, investigator, reporter = fixture_inputs()
    understanding = fixture_understanding_input()
    temperature = 1.0 if provider_name is ProviderName.GEMINI else 0
    reporter_mode = StructuredOutputMode.JSON_SCHEMA if provider_name is ProviderName.GEMINI else StructuredOutputMode.JSON_OBJECT
    return [
        ("understanding", understanding, LLMRequest(
            request_id=f"contract_understanding_{uuid4().hex}", agent_role="understanding",
            messages=(LLMMessage(role="system", content=SYSTEM_PROMPT), LLMMessage(role="user", content=build_user_prompt(understanding))),
            prompt_version="understanding_prompt_v2", generation=LLMGenerationParameters(temperature=temperature),
            expected_schema=UnderstandingOutput.model_json_schema(), structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
            max_output_tokens=1800, timeout_seconds=45,
        ), parse_understanding_output),
        ("planner", planner, request("planner", planner, PlannerOutput.model_json_schema(), "Create a PlannerOutput. Suggested capabilities must be only get_asset_rms.", 700, temperature=temperature), parse_planner_output),
        ("investigator", investigator, request("investigator", investigator, InvestigationDecision.model_json_schema(), "Create exactly one valid InvestigationDecision. Return type=tool_call, a non-empty decision_id and reason_codes, tool_request={\"tool_name\":\"get_asset_rms\",\"arguments\":{\"asset_id\":\"asset_B211\"}}, required_information=[], and supporting_evidence_ids=[]. This is a decision only; do not execute a tool.", 350, temperature=temperature, prompt_version="contract_smoke.v5.investigator"), parse_investigation_decision),
        ("reporter", reporter, request("reporter", reporter, ReporterOutput.model_json_schema(), "Create a ReporterOutput for tractian_engineering_team. Preserve the supplied claim statement and evidence ID exactly. Include every required report field. Do not propose or execute tools.", 900, reporter_mode, temperature), parse_reporter_output),
    ]


def result_entry(component: str, value: object, response, parsed: object | None, error: str | None) -> dict[str, object]:
    usage = response.usage.model_dump(mode="json") if response.usage else None
    return {"component": component, "input": value.model_dump(mode="json"), "output": parsed.model_dump(mode="json") if parsed else None, "provider": response.provider, "model": response.model, "prompt_version": response.metadata.prompt_version, "latency_ms": response.duration_ms, "usage": usage, "finish_reason": response.metadata.finish_reason, "attempt_count": response.metadata.attempt_count, "schema_valid": parsed is not None, "contract_valid": parsed is not None, "error_category": response.error.code.value if response.error else None, "provider_message_sanitized": response.error.message if response.error else None, "error": error}


def validation_error_summary(component: str, output: str | None) -> str | None:
    """Diagnostica incompatibilidade sem persistir resposta bruta do provider."""
    if output is None:
        return None
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return "invalid_json"

    model = {
        "planner": PlannerOutput,
        "understanding": UnderstandingOutput,
        "investigator": InvestigationDecision,
        "reporter": ReporterOutput,
    }[component]
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        details = [
            f"{'.'.join(str(part) for part in item['loc'])}:{item['type']}"
            for item in exc.errors()
        ]
        return "validation_error=" + ",".join(details)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Autoriza exatamente uma chamada Groq por contrato.")
    parser.add_argument("--component", choices=("understanding", "planner", "investigator", "reporter"), help="Restringe a execução a um único contrato.")
    parser.add_argument("--provider", choices=("groq", "gemini"), default="groq", help="Provider real do contract smoke.")
    parser.add_argument("--benchmark", action="store_true", help="Grava o resultado como comparação controlada entre providers.")
    args = parser.parse_args(argv)
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    provider_name = ProviderName(args.provider)
    config = default_provider_configs()[provider_name]
    if not args.execute:
        print(f"{provider_name.value}: READY model={config.model}")
        return 0
    provider = create_provider(config)
    results: list[dict[str, object]] = []
    try:
        selected_cases = [case for case in case_definitions(provider_name) if args.component is None or case[0] == args.component]
        for component, value, llm_request, parser_fn in selected_cases:
            response = provider.infer(llm_request)
            parsed, error = None, None
            try:
                parsed = parser_fn(response)
                if component == "reporter":
                    assert parsed.claims == fixture_conclusion().claims, "Reporter não preservou as claims sintéticas."
            except Exception as exc:
                error = validation_error_summary(component, response.output) or (type(exc).__name__ + ": " + str(exc))
            results.append(result_entry(component, value, response, parsed, error))
            print(f"{component}: contract_valid={parsed is not None} latency_ms={response.duration_ms} usage={'available' if response.usage else 'unavailable'}")
    finally:
        provider.close()
    suffix = f"-{provider_name.value}" if provider_name is not ProviderName.GROQ else ""
    base_path = BENCHMARK_RESULT_PATH if args.benchmark else RESULT_PATH
    result_path = base_path.with_name(f"09-3-provider-comparison{suffix}.json") if args.benchmark else (RESULT_PATH.with_name(f"09-2-real-contract-smoke{suffix}.json") if args.component is None else RESULT_PATH.with_name(f"09-2-real-contract-smoke-{args.component}-v3{suffix}.json"))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_type = "controlled_provider_comparison" if args.benchmark else "real_contract_smoke"
    result_path.write_text(json.dumps({"result_type": result_type, "external_calls": len(results), "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"safe_results={result_path}")
    return 0 if all(item["contract_valid"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

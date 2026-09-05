"""Fase A da avaliação E2E 09.4: somente Synthetic DEV e execução explícita."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter
from time import sleep
from uuid import uuid4

from app.agents.understanding.dataset import UnderstandingSample, load_dev_split
from app.agents.understanding.prompts import PROMPT_VERSION as UNDERSTANDING_PROMPT, SYSTEM_PROMPT, build_user_prompt
from app.agents.understanding.schemas import UnderstandingOutput
from app.intelligence import CapabilityReference, Claim, ClaimStatus, EvidenceSummary, InvestigationConclusion, InvestigatorInput, PlannerInput, PlannerOutput, ReporterInput, ReporterOutput, TraceSummary
from app.intelligence.boundaries import parse_planner_output, parse_reporter_output
from app.integrations.tractian_client import RequestContext, TractianClient
from app.investigation import InvestigationDecision, InvestigationDecisionType, LLMArtifactSource, UnderstandingSource, assess_completion_decision, attach_conclusion, attach_plan, attach_technical_report, attach_understanding, begin_investigation, create_investigation_state, record_decision, synchronize_observability
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, LLMResponseStatus, StructuredOutputMode
from app.llm.investigator import InvestigatorRecoveryAction, recovery_action, validate_investigation_decision
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from app.observability import TrackedToolExecutor
from app.tools import get_investigator_tools
from scripts.diagnose_llm_providers import load_local_env


ROUTING_VERSION = "MODEL_ROUTING_V4"
PILOT_SIZE = 5
ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "experiments" / "e2e-dev-v4"
INVESTIGATOR_PROMPT_VERSION = "e2e_investigator_v4"
INVESTIGATOR_SYSTEM_PROMPT = """Return only one JSON object matching InvestigationDecision exactly.
Allowed type values: continue, tool_call, ask_user, answer, escalate. Never emit ACTION.
Always include decision_id, type, non-empty reason_codes, tool_request, required_information, supporting_evidence_ids.
For tool_call, tool_request is required and must contain one permitted READ tool with schema-valid arguments.
For every non-tool_call decision, tool_request must be null.
For ask_user, required_information must be non-empty; for every other decision it must be empty.
For answer, cite only supporting_evidence_ids present in the input and only when existing evidence is sufficient.
Use ask_user for required external information; use escalate for exhausted, unavailable, inconclusive, or conflicting evidence.
Do not repeat a tool without new evidence. Do not add fields."""


def _request(role: str, messages: tuple[LLMMessage, ...], schema: dict, *, prompt_version: str, max_tokens: int, provider: ProviderName) -> LLMRequest:
    return LLMRequest(
        request_id=f"e2e_{role}_{uuid4().hex}", agent_role=role, messages=messages,
        prompt_version=prompt_version, expected_schema=schema,
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        generation=LLMGenerationParameters(temperature=0.0),
        max_output_tokens=max_tokens, timeout_seconds=45,
    )


def _json(response):
    if response.status is not LLMResponseStatus.SUCCESS:
        raise RuntimeError(response.error.code.value if response.error else "provider_failure")
    return json.loads(response.output) if isinstance(response.output, str) else response.output


def _llm_record(response) -> dict[str, object]:
    return {
        "provider": response.provider, "model": response.model,
        "prompt_version": response.metadata.prompt_version, "latency_ms": response.duration_ms,
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
        "finish_reason": response.metadata.finish_reason,
        "error": response.error.model_dump(mode="json") if response.error else None,
    }


def _investigator_request(value: InvestigatorInput, *, repair: dict[str, object] | None = None) -> LLMRequest:
    messages = [LLMMessage(role="system", content=INVESTIGATOR_SYSTEM_PROMPT)]
    if repair is not None:
        messages.append(LLMMessage(role="user", content=json.dumps({
            "instruction": "The prior output violated the contract. Return one schema-valid replacement. Do not infer or reveal an expected decision.",
            "validation_category": repair["category"], "invalid_field": repair["field"],
            "previous_output_sanitized": repair["output"],
        }, ensure_ascii=False)))
    messages.append(LLMMessage(role="user", content=json.dumps(value.model_dump(mode="json"), ensure_ascii=False)))
    return _request("investigator", tuple(messages), InvestigationDecision.model_json_schema(), prompt_version=INVESTIGATOR_PROMPT_VERSION, max_tokens=700, provider=ProviderName.GEMINI)


def _validation_attempt(provider, response, result, parsed, *, attempt_number: int, value: InvestigatorInput) -> dict[str, object]:
    evidence, trace = value.evidence, value.trace
    return {
        **_llm_record(response),
        "attempt_number": attempt_number,
        "provider_raw_output_sanitized": provider.last_raw_response_sanitized,
        "canonical_llm_response": response.model_dump(mode="json"),
        "json_parser_input": response.output,
        "parsed_json": parsed,
        "validation": result.model_dump(mode="json"),
        "investigation_state_input": value.model_dump(mode="json"),
        "planner_output": value.plan.model_dump(mode="json"),
        "evidence_summary": evidence.model_dump(mode="json"),
        "trace_summary": trace.model_dump(mode="json"),
        "permitted_tools": [item.name for item in value.permitted_capabilities],
    }


def select_pilot(samples: tuple[UnderstandingSample, ...]) -> tuple[UnderstandingSample, ...]:
    """Seleção estável, por tags, sem abrir splits não permitidos."""
    desired = ("easy", "multi_asset", "ambiguity_present", "mixed_or_unclear", "execute_or_handoff_recognition")
    chosen: list[UnderstandingSample] = []
    for tag in desired:
        found = next((sample for sample in samples if tag in sample.training_tags and sample not in chosen), None)
        if found:
            chosen.append(found)
    for sample in samples:
        if len(chosen) == PILOT_SIZE:
            break
        if sample not in chosen:
            chosen.append(sample)
    return tuple(chosen)


def _summaries(state) -> tuple[EvidenceSummary, TraceSummary]:
    records = state.evidence_ledger.records
    events = state.trace.events
    tool_events = [event for event in events if event.tool_name is not None]
    return EvidenceSummary(
        evidence_ids=tuple(item.evidence_id for item in records),
        statuses=tuple(item.evidence_status.value for item in records),
        relevant_results=tuple({"evidence_id": item.evidence_id, "tool_name": item.tool_name, "data": item.data} for item in records[-3:]),
    ), TraceSummary(trace_id=state.trace_id, tool_call_count=state.tool_call_count, last_tool_name=tool_events[-1].tool_name if tool_events else None, last_call_id=tool_events[-1].call_id if tool_events else None)


def _conclusion(state) -> InvestigationConclusion:
    records = state.evidence_ledger.records
    if not records:
        raise ValueError("INSUFFICIENT_EVIDENCE")
    supporting = tuple(record.evidence_id for record in records if record.evidence_status.value not in {"conflict", "unavailable"})
    contradictory = tuple(record.evidence_id for record in records if record.evidence_status.value == "conflict")
    referenced = supporting or contradictory or (records[-1].evidence_id,)
    status = ClaimStatus.SUPPORTED if supporting else ClaimStatus.UNRESOLVED
    claim = Claim(
        claim_id=f"claim_{state.case_id}",
        statement="A conclusão é limitada às evidências registradas nesta execução sintética.",
        supporting_evidence_ids=referenced,
        contradictory_evidence_ids=contradictory,
        limitation="Conclusão determinística de piloto; não substitui revisão de engenharia.",
        status=status,
    )
    return InvestigationConclusion(
        conclusion_id=f"conclusion_{state.case_id}", claims=(claim,),
        supporting_evidence_ids=referenced, contradictory_evidence_ids=contradictory,
        limitations=("Piloto E2E sintético com evidência limitada às READ tools executadas.",),
        unresolved_points=(), reason_codes=("E2E_SYNTHETIC_EVIDENCE",),
    )


def run_case(sample: UnderstandingSample, providers: dict[ProviderName, object], client: TractianClient) -> dict[str, object]:
    started = perf_counter()
    errors: list[str] = []
    terminal_status = "DEAD_END"
    components: dict[str, object] = {}
    runtime = create_investigation_state(sample.input, case_id=f"case_{sample.sample_id}", request_id=f"request_{sample.sample_id}", trace_id=f"trace_{sample.sample_id}")
    executor = TrackedToolExecutor(client, runtime.trace, runtime.evidence_ledger)
    tools = {tool.name: tool for tool in get_investigator_tools()}
    state = runtime.state
    try:
        # Understanding / Groq
        response = providers[ProviderName.GROQ].infer(_request("understanding", (LLMMessage(role="system", content=SYSTEM_PROMPT), LLMMessage(role="user", content=build_user_prompt(sample.input))), UnderstandingOutput.model_json_schema(), prompt_version="understanding_prompt_v2", max_tokens=1800, provider=ProviderName.GROQ))
        components["understanding"] = _llm_record(response)
        understanding = UnderstandingOutput.model_validate(_json(response))
        state = attach_understanding(state, understanding, source=UnderstandingSource.MODEL)
        components["understanding"]["output"] = understanding.model_dump(mode="json")

        # Planner / Gemini
        planner_input = PlannerInput(understanding=understanding, permitted_context={"source": "synthetic_dev_e2e"}, available_capabilities=tuple(CapabilityReference(name=name) for name in tools), max_investigation_steps=state.max_investigation_steps, max_tool_calls=state.max_tool_calls)
        response = providers[ProviderName.GEMINI].infer(_request("planner", (LLMMessage(role="system", content="Return only a JSON object. Plan a read-only investigation; do not execute tools or propose ACTIONs."), LLMMessage(role="user", content=json.dumps(planner_input.model_dump(mode="json"), ensure_ascii=False))), PlannerOutput.model_json_schema(), prompt_version="e2e_planner_v1", max_tokens=900, provider=ProviderName.GEMINI))
        components["planner"] = _llm_record(response)
        plan = parse_planner_output(response)
        state = attach_plan(state, plan, source=LLMArtifactSource.REAL_LLM)
        components["planner"]["output"] = plan.model_dump(mode="json")
        state = begin_investigation(state)

        # Investigator loop / Gemini
        decisions: list[dict[str, object]] = []
        while state.investigation_step_count < state.max_investigation_steps:
            evidence, trace = _summaries(state)
            value = InvestigatorInput(understanding=understanding, plan=plan, phase=state.phase.value, evidence=evidence, trace=trace, permitted_capabilities=tuple(CapabilityReference(name=name) for name in tools), investigation_step_count=state.investigation_step_count, max_investigation_steps=state.max_investigation_steps, tool_call_count=state.tool_call_count, max_tool_calls=state.max_tool_calls)
            provider = providers[ProviderName.GEMINI]
            response = provider.infer(_investigator_request(value))
            validation, proposed, parsed = validate_investigation_decision(response)
            attempts = [_validation_attempt(provider, response, validation, parsed, attempt_number=1, value=value)]
            repair_attempted = False
            if not validation.valid and recovery_action(validation) is InvestigatorRecoveryAction.ONE_LLM_REPAIR:
                repair_attempted = True
                repair_context = {"category": validation.category.value if validation.category else None, "field": validation.field, "output": parsed if parsed is not None else response.output}
                response = provider.infer(_investigator_request(value, repair=repair_context))
                validation, proposed, parsed = validate_investigation_decision(response)
                attempts.append(_validation_attempt(provider, response, validation, parsed, attempt_number=2, value=value))
            if not validation.valid or proposed is None:
                category = validation.category.value if validation.category else "OTHER_CONTRACT_VIOLATION"
                errors.append(f"INVESTIGATOR_VALIDATION:{category}")
                decision = InvestigationDecision(decision_id=f"contract_fail_safe_{uuid4().hex}", type=InvestigationDecisionType.ESCALATE, reason_codes=("INVESTIGATOR_CONTRACT_FAILURE",))
                decisions.append({"attempts": attempts, "first_pass_valid": attempts[0]["validation"]["valid"], "repair_attempted": repair_attempted, "repair_successful": False, "final_decision_source": "deterministic_fail_safe", "output": decision.model_dump(mode="json")})
                state = record_decision(state, decision)
                break
            assessment = assess_completion_decision(state, proposed)
            decision = assessment.decision
            decisions.append({
                "attempts": attempts,
                "first_pass_valid": attempts[0]["validation"]["valid"],
                "repair_attempted": repair_attempted,
                "repair_successful": repair_attempted and validation.valid,
                "final_decision_source": "repaired_llm" if repair_attempted else "first_pass_llm",
                "output": decision.model_dump(mode="json"),
                "completion_policy": {
                    "accepted": assessment.accepted,
                    "reason_code": assessment.reason_code,
                    "rejected_decision_type": assessment.rejected_decision_type.value if assessment.rejected_decision_type else None,
                },
            })
            state = record_decision(state, decision)
            if decision.type is InvestigationDecisionType.TOOL_CALL:
                assert decision.tool_request is not None
                result = executor.execute(tools[decision.tool_request.tool_name], decision.tool_request.arguments)
                state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
                if not result.transport_ok:
                    errors.append("TOOL_EXECUTION_ERROR")
                    break
                continue
            break
        components["investigator"] = decisions

        # Conclusion + Reporter only after a grounded answer.
        if state.decision and state.decision.type is InvestigationDecisionType.ANSWER:
            conclusion = _conclusion(state)
            state = attach_conclusion(state, conclusion)
            evidence, trace = _summaries(state)
            reporter_input = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=understanding, plan=plan, conclusion=conclusion, evidence=evidence, trace=trace)
            response = providers[ProviderName.GEMINI].infer(_request("reporter", (LLMMessage(role="system", content="Return only a ReporterOutput JSON for tractian_engineering_team. Preserve supplied claims and evidence IDs exactly; do not invent facts."), LLMMessage(role="user", content=json.dumps(reporter_input.model_dump(mode="json"), ensure_ascii=False))), ReporterOutput.model_json_schema(), prompt_version="e2e_reporter_v1", max_tokens=1200, provider=ProviderName.GEMINI))
            report = parse_reporter_output(response)
            state = attach_technical_report(state, report, source=LLMArtifactSource.REAL_LLM)
            components["reporter"] = {**_llm_record(response), "output": report.model_dump(mode="json")}
            terminal_status = "GROUNDED_COMPLETION"
        elif state.decision and state.decision.type is InvestigationDecisionType.ESCALATE:
            terminal_status = "SAFE_ESCALATION"
        elif state.decision and state.decision.type is InvestigationDecisionType.ASK_USER:
            terminal_status = "AWAITING_REQUIRED_INFORMATION"
        else:
            errors.append("INSUFFICIENT_EVIDENCE" if not state.evidence_ledger.records else "INVESTIGATION_NOT_ANSWERED")
    except Exception as exc:
        errors.append(type(exc).__name__)

    return {
        "run_id": f"pilot_{sample.sample_id}", "sample_id": sample.sample_id, "routing_version": ROUTING_VERSION,
        "training_tags": list(sample.training_tags), "providers": {"understanding": "groq", "planner": "gemini", "investigator": "gemini", "reporter": "gemini"},
        "components": components, "state": state.model_dump(mode="json"), "trace": runtime.trace.as_dicts(), "evidence_ledger": runtime.evidence_ledger.as_dicts(),
        "terminal_status": terminal_status, "errors": errors, "latency_ms": round((perf_counter() - started) * 1000, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Autoriza somente a Fase A, com cinco casos DEV.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--throttle-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)
    load_local_env(ROOT / "api" / ".env")
    samples = select_pilot(load_dev_split())
    configs = default_provider_configs()
    if not args.execute:
        print(f"READY pilot_sample_ids={[sample.sample_id for sample in samples]}")
        return 0
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise RuntimeError(f"Diretório experimental já contém artefatos: {OUTPUT_DIR}")
    providers = {name: create_provider(configs[name]) for name in (ProviderName.GROQ, ProviderName.GEMINI)}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with TractianClient(RequestContext(), base_url=args.api_base_url) as client:
            runs = []
            for index, sample in enumerate(samples):
                if index:
                    sleep(args.throttle_seconds)
                runs.append(run_case(sample, providers, client))
    finally:
        for provider in providers.values(): provider.close()
    (OUTPUT_DIR / "runs.jsonl").write_text("".join(json.dumps(run, ensure_ascii=False) + "\n" for run in runs), encoding="utf-8")
    errors = [error for run in runs for error in run["errors"]]
    component_metrics = []
    for component in ("understanding", "planner", "investigator", "reporter"):
        entries = [run["components"].get(component) for run in runs]
        calls = sum(len(entry) if isinstance(entry, list) else int(entry is not None) for entry in entries)
        component_metrics.append({"component": component, "cases_reached": sum(entry is not None for entry in entries), "llm_calls": calls})
    all_decisions = [decision for run in runs for decision in run["components"].get("investigator", [])]
    total_decisions = len(all_decisions)
    validation_errors = [attempt["validation"] for decision in all_decisions for attempt in decision["attempts"] if not attempt["validation"]["valid"]]
    terminal_counts = Counter(run["terminal_status"] for run in runs)
    metrics = {
        "cases": len(runs), "completed_reports": sum("reporter" in run["components"] for run in runs), "errors": dict(Counter(errors)),
        "tool_calls": sum(len(run["trace"]) // 2 for run in runs), "llm_calls": sum(item["llm_calls"] for item in component_metrics) + sum(bool(decision["repair_attempted"]) for decision in all_decisions), "routing_version": ROUTING_VERSION,
        "investigator_first_pass_valid_rate": (sum(bool(item["first_pass_valid"]) for item in all_decisions) / total_decisions) if total_decisions else 0,
        "investigator_repair_rate": (sum(bool(item["repair_attempted"]) for item in all_decisions) / total_decisions) if total_decisions else 0,
        "investigator_failed_validation_rate": (sum(item["final_decision_source"] == "deterministic_fail_safe" for item in all_decisions) / total_decisions) if total_decisions else 0,
        "validation_error_by_category": dict(Counter(item["category"] for item in validation_errors)),
        "validation_error_by_field": dict(Counter(item["field"] or "<root>" for item in validation_errors)),
        "dead_end_due_to_contract_rate": sum(run["terminal_status"] == "DEAD_END" and any(str(error).startswith("INVESTIGATOR_VALIDATION:") for error in run["errors"]) for run in runs) / len(runs),
        "terminal_state_rate": {key: value / len(runs) for key, value in terminal_counts.items()},
        "grounded_completion_rate": terminal_counts["GROUNDED_COMPLETION"] / len(runs), "safe_escalation_rate": terminal_counts["SAFE_ESCALATION"] / len(runs),
        "awaiting_information_rate": terminal_counts["AWAITING_REQUIRED_INFORMATION"] / len(runs), "dead_end_rate": terminal_counts["DEAD_END"] / len(runs),
        "reporter_reach_rate": sum("reporter" in run["components"] for run in runs) / len(runs),
    }
    (OUTPUT_DIR / "aggregate-metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "component-metrics.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in component_metrics), encoding="utf-8")
    (OUTPUT_DIR / "errors.jsonl").write_text("".join(json.dumps({"run_id": run["run_id"], "sample_id": run["sample_id"], "errors": run["errors"]}, ensure_ascii=False) + "\n" for run in runs if run["errors"]), encoding="utf-8")
    showcase = {"routing_version": ROUTING_VERSION, "cases": [{"sample_id": run["sample_id"], "errors": run["errors"], "components": run["components"], "trace": run["trace"], "evidence_ledger": run["evidence_ledger"]} for run in runs]}
    (OUTPUT_DIR / "showcase.json").write_text(json.dumps(showcase, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    routing = {"understanding": {"provider": "groq", "model": configs[ProviderName.GROQ].model}, "planner": {"provider": "gemini", "model": configs[ProviderName.GEMINI].model}, "investigator": {"provider": "gemini", "model": configs[ProviderName.GEMINI].model}, "reporter": {"provider": "gemini", "model": configs[ProviderName.GEMINI].model}}
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps({"experiment_version": "e2e-dev-v4", "routing_version": ROUTING_VERSION, "routing": routing, "prompt_version": INVESTIGATOR_PROMPT_VERSION, "schema_version": "InvestigationDecision-1.0", "adapter_version": "gemini-http-v2-diagnostics", "recovery_policy": "one_llm_repair_then_deterministic_safe_escalation", "split": "synthetic_dev", "sample_ids": [sample.sample_id for sample in samples], "forbidden_splits_not_loaded": ["train", "holdout", "golden"], "phase": "A_PILOT"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

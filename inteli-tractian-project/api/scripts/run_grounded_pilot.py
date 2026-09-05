"""Micro-piloto positivo 09.4F; uma fixture de integração, sem valor de benchmark."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.agents.understanding.prompts import SYSTEM_PROMPT, build_user_prompt
from app.agents.understanding.schemas import AvailableContext, UnderstandingInput, UnderstandingOutput
from app.intelligence import CapabilityReference, InvestigatorInput, PlannerInput, PlannerOutput, ReporterInput, ReporterOutput
from app.intelligence.grounding import build_claim_lineage, build_grounded_conclusion, validate_reporter_output
from app.intelligence.boundaries import parse_planner_output, parse_reporter_output
from app.integrations.tractian_client import RequestContext, TractianClient
from app.investigation import InvestigationDecision, InvestigationDecisionType, LLMArtifactSource, UnderstandingSource, assess_completion_decision, attach_conclusion, attach_plan, attach_technical_report, attach_understanding, begin_investigation, create_investigation_state, record_decision, synchronize_observability
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, StructuredOutputMode
from app.llm.investigator import InvestigatorRecoveryAction, recovery_action, validate_investigation_decision
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from app.observability import RunTiming, TraceEventType, TrackedToolExecutor
from app.tools import get_investigator_tools
from scripts.diagnose_llm_providers import load_local_env
from scripts.run_e2e_dev_pilot import INVESTIGATOR_PROMPT_VERSION, _investigator_request, _llm_record, _summaries, _validation_attempt


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "experiments" / "e2e-grounded-pilot-v1"
EXPERIMENT_VERSION = "e2e-grounded-pilot-v1"
ROUTING_VERSION = "MODEL_ROUTING_V4"
FIXTURE_ID = "integration_fixture_asset_s425_facts_v1"
READ_OPERATIONS = frozenset(tool.client_operation for tool in get_investigator_tools())


def integration_request() -> UnderstandingInput:
    return UnderstandingInput(
        message="Consulte o cadastro atual do asset_S425 e informe seu nome, tipo, criticidade e status do sensor. Responda apenas com os campos retornados pela fonte e preserve qualquer limitação.",
        available_context=AvailableContext(tenant_ref="integration_fixture", asset_refs=("asset_S425",), role="reliability_analyst", permissions=("read",)),
    )


class DeterministicReadClient:
    """Proxy de integração que fixa `seed=complete`; continua expondo só READs do Registry."""

    def __init__(self, client: TractianClient) -> None:
        self._client = client

    def __getattr__(self, name: str):
        if name not in READ_OPERATIONS:
            raise AttributeError(name)
        operation = getattr(self._client, name)
        def invoke(*args, **kwargs):
            kwargs["seed"] = "complete"
            return operation(*args, **kwargs)
        return invoke


def _request(role: str, prompt: str, payload: object, schema: dict, version: str, max_tokens: int, request_id: str) -> LLMRequest:
    return LLMRequest(
        request_id=request_id, agent_role=role,
        messages=(LLMMessage(role="system", content=prompt), LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False))),
        prompt_version=version, generation=LLMGenerationParameters(temperature=0.0), expected_schema=schema,
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA, max_output_tokens=max_tokens, timeout_seconds=45,
    )


def execute_case(providers: dict[ProviderName, object], client: TractianClient) -> dict[str, object]:
    started_at = datetime.now(timezone.utc)
    request = integration_request()
    runtime = create_investigation_state(request, case_id=FIXTURE_ID, request_id=f"request_{FIXTURE_ID}", trace_id=f"trace_{FIXTURE_ID}")
    state = runtime.state
    tools = {tool.name: tool for tool in get_investigator_tools()}
    executor = TrackedToolExecutor(DeterministicReadClient(client), runtime.trace, runtime.evidence_ledger)  # type: ignore[arg-type]
    components: dict[str, object] = {}
    errors: list[str] = []
    terminal = "DEAD_END"
    try:
        response = providers[ProviderName.GROQ].infer(_request("understanding", SYSTEM_PROMPT, build_user_prompt(request), UnderstandingOutput.model_json_schema(), "understanding_prompt_v2", 1800, f"grounded_understanding_{uuid4().hex}"))
        understanding = UnderstandingOutput.model_validate(json.loads(response.output) if isinstance(response.output, str) else response.output)
        components["understanding"] = {**_llm_record(response), "input": request.model_dump(mode="json"), "output": understanding.model_dump(mode="json"), "schema_valid": True}
        state = attach_understanding(state, understanding, source=UnderstandingSource.MODEL)

        planner_input = PlannerInput(understanding=understanding, permitted_context={"fixture_type": "INTEGRATION_FIXTURE"}, available_capabilities=tuple(CapabilityReference(name=name) for name in tools), max_investigation_steps=state.max_investigation_steps, max_tool_calls=state.max_tool_calls)
        response = providers[ProviderName.GEMINI].infer(_request("planner", "Plan a read-only factual lookup. Return only PlannerOutput JSON. Do not execute tools or propose ACTIONs.", planner_input.model_dump(mode="json"), PlannerOutput.model_json_schema(), "e2e_planner_v1", 900, f"grounded_planner_{uuid4().hex}"))
        plan = parse_planner_output(response)
        components["planner"] = {**_llm_record(response), "output": plan.model_dump(mode="json"), "schema_valid": True}
        state = begin_investigation(attach_plan(state, plan, source=LLMArtifactSource.REAL_LLM))

        decisions: list[dict[str, object]] = []
        while state.investigation_step_count < state.max_investigation_steps:
            evidence, trace = _summaries(state)
            value = InvestigatorInput(understanding=understanding, plan=plan, phase=state.phase.value, evidence=evidence, trace=trace, permitted_capabilities=tuple(CapabilityReference(name=name) for name in tools), investigation_step_count=state.investigation_step_count, max_investigation_steps=state.max_investigation_steps, tool_call_count=state.tool_call_count, max_tool_calls=state.max_tool_calls)
            provider = providers[ProviderName.GEMINI]
            response = provider.infer(_investigator_request(value))
            runtime.trace.append_operational(TraceEventType.LLM_DECISION_PRODUCED, f"decision_output_{uuid4().hex}", details={"provider": response.provider, "model": response.model, "prompt_version": INVESTIGATOR_PROMPT_VERSION})
            validation, proposed, parsed = validate_investigation_decision(response)
            attempts = [_validation_attempt(provider, response, validation, parsed, attempt_number=1, value=value)]
            repaired = False
            if not validation.valid and recovery_action(validation) is InvestigatorRecoveryAction.ONE_LLM_REPAIR:
                repaired = True
                response = provider.infer(_investigator_request(value, repair={"category": validation.category.value if validation.category else None, "field": validation.field, "output": parsed if parsed is not None else response.output}))
                validation, proposed, parsed = validate_investigation_decision(response)
                attempts.append(_validation_attempt(provider, response, validation, parsed, attempt_number=2, value=value))
            runtime.trace.append_operational(TraceEventType.DECISION_VALIDATED, f"decision_validation_{uuid4().hex}", details={"valid": validation.valid, "category": validation.category.value if validation.category else None, "repair_attempted": repaired})
            if not validation.valid or proposed is None:
                errors.append(f"INVESTIGATOR_VALIDATION:{validation.category.value if validation.category else 'UNKNOWN'}")
                break
            assessment = assess_completion_decision(state, proposed)
            decision = assessment.decision
            runtime.trace.append_operational(TraceEventType.DECISION_ACCEPTED if assessment.accepted else TraceEventType.DECISION_REJECTED, decision.decision_id, details={"decision_type": decision.type.value, "policy_reason": assessment.reason_code})
            decisions.append({"attempts": attempts, "first_pass_valid": attempts[0]["validation"]["valid"], "repair_attempted": repaired, "output": decision.model_dump(mode="json"), "completion_policy": {"accepted": assessment.accepted, "reason_code": assessment.reason_code}})
            state = record_decision(state, decision)
            if decision.type is InvestigationDecisionType.TOOL_CALL:
                assert decision.tool_request is not None
                runtime.trace.append_operational(TraceEventType.TOOL_REQUESTED, decision.decision_id, details={"tool_name": decision.tool_request.tool_name})
                result = executor.execute(tools[decision.tool_request.tool_name], decision.tool_request.arguments)
                state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
                if not result.transport_ok:
                    errors.append("TOOL_EXECUTION_ERROR")
                    break
                continue
            break
        components["investigator"] = decisions
        state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)

        if state.decision and state.decision.type is InvestigationDecisionType.ANSWER:
            conclusion = build_grounded_conclusion(state)
            lineage = build_claim_lineage(state, conclusion)
            if not all(item.valid for item in lineage):
                raise ValueError("INVALID_CLAIM_LINEAGE")
            state = attach_conclusion(state, conclusion)
            runtime.trace.append_operational(TraceEventType.CONCLUSION_CREATED, conclusion.conclusion_id, details={"claim_count": len(conclusion.claims), "lineage_valid": True})
            state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            evidence, trace = _summaries(state)
            reporter_input = ReporterInput(case_id=state.case_id, trace_id=state.trace_id, understanding=understanding, plan=plan, conclusion=conclusion, evidence=evidence, trace=trace)
            runtime.trace.append_operational(TraceEventType.REPORTER_STARTED, f"reporter_{uuid4().hex}", details={"audience": "tractian_engineering_team"})
            reporter_prompt = "Return only ReporterOutput JSON for tractian_engineering_team. Copy every supplied claim, evidence ID, limitation and unresolved point exactly. Do not add claims, facts, tools or actions."
            response = providers[ProviderName.GEMINI].infer(_request("reporter", reporter_prompt, reporter_input.model_dump(mode="json"), ReporterOutput.model_json_schema(), "e2e_reporter_grounded_v1", 1200, f"grounded_reporter_{uuid4().hex}"))
            report = parse_reporter_output(response)
            reporter_validation = validate_reporter_output(reporter_input, report)
            if not reporter_validation.valid:
                runtime.trace.append_operational(TraceEventType.REPORTER_FAILED, report.report_id, details={"violations": list(reporter_validation.violations)})
                raise ValueError("REPORTER_GROUNDING_VALIDATION_FAILED")
            state = attach_technical_report(state, report, source=LLMArtifactSource.REAL_LLM)
            runtime.trace.append_operational(TraceEventType.REPORTER_COMPLETED, report.report_id, details={"schema_valid": True, "unsupported_claim_rate": 0.0})
            state = synchronize_observability(state, runtime.trace, runtime.evidence_ledger)
            components["conclusion"] = conclusion.model_dump(mode="json")
            components["claim_lineage"] = [item.model_dump(mode="json") for item in lineage]
            components["reporter"] = {**_llm_record(response), "input": reporter_input.model_dump(mode="json"), "output": report.model_dump(mode="json"), "validation": reporter_validation.model_dump(mode="json")}
            terminal = "GROUNDED_COMPLETION"
        elif state.decision and state.decision.type is InvestigationDecisionType.ASK_USER:
            terminal = "AWAITING_REQUIRED_INFORMATION"
        elif state.decision and state.decision.type is InvestigationDecisionType.ESCALATE:
            terminal = "SAFE_ESCALATION"
    except Exception as exc:
        errors.append(type(exc).__name__ + ":" + str(exc)[:200])
    finished_at = datetime.now(timezone.utc)
    timing = RunTiming.between(started_at, finished_at)
    return {"run_id": f"run_{FIXTURE_ID}", "fixture_type": "INTEGRATION_FIXTURE", "case_id": FIXTURE_ID, **timing.model_dump(mode="json"), "routing_version": ROUTING_VERSION, "components": components, "state": state.model_dump(mode="json"), "trace": runtime.trace.as_dicts(), "evidence_ledger": runtime.evidence_ledger.as_dicts(), "terminal_status": terminal, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args(argv)
    load_local_env(ROOT / "api" / ".env")
    configs = default_provider_configs()
    if not args.execute:
        print(f"READY fixture={FIXTURE_ID} split_access=none output={OUTPUT_DIR}")
        return 0
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        raise RuntimeError(f"Diretório experimental já contém artefatos: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    providers = {name: create_provider(configs[name]) for name in (ProviderName.GROQ, ProviderName.GEMINI)}
    try:
        with TractianClient(RequestContext(), base_url=args.api_base_url) as client:
            run_case = execute_case(providers, client)
    finally:
        for provider in providers.values(): provider.close()
    llm_entries = [run_case["components"].get("understanding"), run_case["components"].get("planner"), run_case["components"].get("reporter")]
    llm_entries += [attempt for decision in run_case["components"].get("investigator", []) for attempt in decision["attempts"]]
    llm_entries = [item for item in llm_entries if item]
    usage = {"input_tokens": sum((item.get("usage") or {}).get("input_tokens", 0) for item in llm_entries), "output_tokens": sum((item.get("usage") or {}).get("output_tokens", 0) for item in llm_entries), "total_tokens": sum((item.get("usage") or {}).get("total_tokens", 0) for item in llm_entries)}
    metrics = {"candidate_cases": 1, "executed_cases": 1, "grounded_completions": int(run_case["terminal_status"] == "GROUNDED_COMPLETION"), "safe_escalations": int(run_case["terminal_status"] == "SAFE_ESCALATION"), "awaiting_information": int(run_case["terminal_status"] == "AWAITING_REQUIRED_INFORMATION"), "dead_ends": int(run_case["terminal_status"] == "DEAD_END"), "first_pass_valid_rate": sum(decision["first_pass_valid"] for decision in run_case["components"].get("investigator", [])) / max(1, len(run_case["components"].get("investigator", []))), "repair_rate": sum(decision["repair_attempted"] for decision in run_case["components"].get("investigator", [])) / max(1, len(run_case["components"].get("investigator", []))), "tool_calls": len(run_case["evidence_ledger"]), "steps": len(run_case["components"].get("investigator", [])), "evidence_records": len(run_case["evidence_ledger"]), "reporter_reach_rate": float("reporter" in run_case["components"]), "reporter_completion_rate": float("reporter" in run_case["components"] and run_case["components"]["reporter"]["validation"]["valid"]), "usage": usage, "provider_calls": len(llm_entries), "provider_latency_ms": round(sum(item.get("latency_ms", 0) for item in llm_entries), 3), "errors": dict(Counter(run_case["errors"]))}
    manifest = {"experiment_version": EXPERIMENT_VERSION, "routing_version": ROUTING_VERSION, "fixture_type": "INTEGRATION_FIXTURE", "fixture_id": FIXTURE_ID, "selection_reason": "Cadastro S425 existe e contém todos os campos factuais solicitados.", "available_data": ["assets.parquet:asset_S425"], "candidate_tools": ["get_asset_context"], "expected_evidence_characteristics": ["non_empty", "complete", "factual_asset_fields"], "expected_answer": None, "deterministic_api_seed": "complete", "protected_splits_accessed": False, "routing": {name.value: configs[name].model for name in providers}}
    for name, value in (("manifest.json", manifest), ("metrics.json", metrics), ("showcase.json", run_case)):
        (OUTPUT_DIR / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "runs.jsonl").write_text(json.dumps(run_case, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "errors.jsonl").write_text((json.dumps({"run_id": run_case["run_id"], "errors": run_case["errors"]}, ensure_ascii=False) + "\n") if run_case["errors"] else "", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))
    return 0 if run_case["terminal_status"] == "GROUNDED_COMPLETION" and not run_case["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

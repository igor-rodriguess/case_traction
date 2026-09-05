"""Verificação causal do teto de saída do Gemini (Etapa 09.6, §3).

A Etapa 09.5 perdeu quatro casos com `finish=MAX_TOKENS` a ~496 tokens de saída,
porque `ProviderConfig.max_output_tokens` tinha default 512 e o adapter aplica
`min(request, config)`. Este script reexecuta exatamente aqueles Planners, com o
mesmo input gravado na V1 e o teto corrigido, e persiste o antes/depois.

Reusar o `UnderstandingOutput` já registrado isola a variável: o único elemento
diferente entre V1 e V2 é o orçamento de saída.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agents.understanding.schemas import UnderstandingOutput
from app.intelligence import CapabilityReference, PlannerInput, PlannerOutput
from app.intelligence.boundaries import parse_planner_output
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, StructuredOutputMode
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from app.tools import get_investigator_tools
from scripts.diagnose_llm_providers import load_local_env
from scripts.run_full_dev_evaluation import PLANNER_MAX_TOKENS, PLANNER_SYSTEM_PROMPT


ROOT = Path(__file__).resolve().parents[2]
V1_RUNS = ROOT / "experiments" / "e2e-full-dev-v1" / "runs.jsonl"
OUTPUT = ROOT / "experiments" / "e2e-full-dev-v2-smoke" / "planner-token-repair.json"


def truncated_cases() -> list[dict]:
    """Casos cuja falha de Planner na V1 foi corte por orçamento, não conteúdo."""

    cases = []
    for line in V1_RUNS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        run = json.loads(line)
        planner = run.get("components", {}).get("planner") or {}
        if planner.get("schema_valid") is False and planner.get("finish_reason") == "MAX_TOKENS":
            cases.append(run)
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verifica o reparo do teto de tokens do Planner.")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    load_local_env(ROOT / "api" / ".env")
    cases = truncated_cases()
    config = default_provider_configs()[ProviderName.GEMINI]
    if not args.execute:
        print(json.dumps({"status": "READY", "truncated_cases": [run["sample_id"] for run in cases]}, ensure_ascii=False))
        return 0

    tools = [tool.name for tool in get_investigator_tools()]
    results = []
    provider = create_provider(config)
    try:
        for run in cases:
            before = run["components"]["planner"]
            understanding = UnderstandingOutput.model_validate(run["components"]["understanding"]["output"])
            value = PlannerInput(
                understanding=understanding,
                permitted_context={"source": "synthetic_dev_full", "split": "dev"},
                available_capabilities=tuple(CapabilityReference(name=name) for name in tools),
                max_investigation_steps=12,
                max_tool_calls=8,
            )
            response = provider.infer(
                LLMRequest(
                    request_id=f"repair_planner_{run['sample_id']}",
                    agent_role="planner",
                    messages=(
                        LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=json.dumps(value.model_dump(mode="json"), ensure_ascii=False)),
                    ),
                    prompt_version="e2e_planner_v1",
                    generation=LLMGenerationParameters(temperature=0.0),
                    expected_schema=PlannerOutput.model_json_schema(),
                    structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
                    max_output_tokens=PLANNER_MAX_TOKENS,
                    timeout_seconds=45,
                )
            )
            schema_valid = False
            if response.status.value == "success":
                try:
                    parse_planner_output(response)
                    schema_valid = True
                except Exception:
                    schema_valid = False
            results.append(
                {
                    "sample_id": run["sample_id"],
                    "v1": {
                        "finish_reason": before.get("finish_reason"),
                        "output_tokens": (before.get("usage") or {}).get("output_tokens"),
                        "schema_valid": before.get("schema_valid"),
                        "effective_output_ceiling": 512,
                    },
                    "v2": {
                        "finish_reason": response.metadata.finish_reason,
                        "output_tokens": response.usage.output_tokens if response.usage else None,
                        "schema_valid": schema_valid,
                        "status": response.status.value,
                        "error": response.error.code.value if response.error else None,
                        "effective_output_ceiling": min(PLANNER_MAX_TOKENS, config.max_output_tokens),
                    },
                }
            )
            print(f"{run['sample_id']}: V1 {before.get('finish_reason')} -> V2 {response.metadata.finish_reason} schema_valid={schema_valid}")
    finally:
        provider.close()

    repaired = sum(item["v2"]["schema_valid"] for item in results)
    payload = {
        "verification": "planner_output_token_ceiling_repair",
        "provider_ceiling_v1": 512,
        "provider_ceiling_v2": config.max_output_tokens,
        "role_budget": PLANNER_MAX_TOKENS,
        "cases_truncated_in_v1": len(results),
        "cases_valid_after_repair": repaired,
        "exceeded_old_ceiling": [item["sample_id"] for item in results if (item["v2"]["output_tokens"] or 0) > 512],
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"repaired": repaired, "of": len(results), "artifact": str(OUTPUT)}, ensure_ascii=False))
    return 0 if repaired == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

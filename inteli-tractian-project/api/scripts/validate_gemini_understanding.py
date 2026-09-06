"""Etapa 09.8 — valida o Gemini como Understanding alternativo.

A pergunta não é "qual provider é melhor", e sim: o Gemini produz
`UnderstandingOutput` compatível e semanticamente defensável o bastante para o
desenvolvimento continuar sem depender da cota diária do Groq?

Duas fases, ambas somente do Understanding:

- `--smoke`: cinco fixtures pequenas, uma por classe, para checar o contrato.
- `--equivalence`: dez casos DEV **já medidos** com Groq na V2, para comparar as
  duas saídas sobre exatamente o mesmo input.

O `target` do DEV só é lido depois da inferência, na camada de avaliação. Nenhum
detalhe do Gemini atravessa o Understanding Agent: o caminho continua sendo
UnderstandingInput → LLMProvider → adapter → LLMResponse canônica → Pydantic.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.agents.understanding.dataset import load_dev_split
from app.agents.understanding.prompts import PROMPT_VERSION_V2, SYSTEM_PROMPT_V2, build_user_prompt
from app.agents.understanding.schemas import AvailableContext, UnderstandingInput, UnderstandingOutput
from app.evaluation.dataset_validation import runtime_payload
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, LLMResponseStatus, StructuredOutputMode
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from scripts.diagnose_llm_providers import load_local_env


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "experiments" / "gemini-understanding-validation"
V2_RUNS = ROOT / "experiments" / "e2e-full-dev-v2" / "runs.jsonl"
MAX_TOKENS = 2048
EQUIVALENCE_SIZE = 10

_IDENTIFIER_BUCKETS = ("assets", "analyses", "models")

# Fixtures de contrato escritas para esta etapa, fora de qualquer split. Não são
# benchmark e não possuem expected answer: existem só para exercitar as cinco
# classes contra o schema.
SMOKE_FIXTURES: tuple[tuple[str, str], ...] = (
    ("contextualize", "O que significa vibracao RMS para o asset_S425?"),
    ("investigate", "A vibracao do asset_S425 mudou? Verifique os dados disponiveis."),
    ("execute", "Verifique o asset_S425 e, se houver evidencia, quero pedir reprocessamento da analise."),
    ("mixed", "De uma olhada naquele equipamento e, se precisar mexer em algo, me avise."),
    ("unclear", "Aquilo que conversamos continua estranho."),
)


def _request(payload: UnderstandingInput, request_id: str) -> LLMRequest:
    return LLMRequest(
        request_id=request_id,
        agent_role="understanding",
        messages=(
            LLMMessage(role="system", content=SYSTEM_PROMPT_V2),
            LLMMessage(role="user", content=build_user_prompt(payload)),
        ),
        prompt_version=PROMPT_VERSION_V2,
        generation=LLMGenerationParameters(temperature=0.0),
        expected_schema=UnderstandingOutput.model_json_schema(),
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        max_output_tokens=MAX_TOKENS,
        timeout_seconds=45,
    )


def _infer(provider, payload: UnderstandingInput, request_id: str) -> dict:
    """Executa e normaliza; contrato quebrado é resultado medido, não exceção."""

    response = provider.infer(_request(payload, request_id))
    record: dict = {
        "status": response.status.value,
        "provider": response.provider,
        "model": response.model,
        "latency_ms": response.duration_ms,
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
        "finish_reason": response.metadata.finish_reason,
        "error": response.error.model_dump(mode="json") if response.error else None,
        "schema_valid": False,
        "output": None,
    }
    if response.status is not LLMResponseStatus.SUCCESS:
        return record
    try:
        raw = json.loads(response.output) if isinstance(response.output, str) else response.output
        record["output"] = UnderstandingOutput.model_validate(raw).model_dump(mode="json")
        record["schema_valid"] = True
    except Exception as exc:
        record["schema_error"] = type(exc).__name__
    return record


def _identifiers(payload: dict) -> set[str]:
    bucket = payload.get("entities") or {}
    return {f"{name}:{value}" for name in _IDENTIFIER_BUCKETS for value in bucket.get(name, [])}


def select_equivalence_cases() -> tuple[list[str], dict[str, int]]:
    """Dez casos já medidos com Groq, estratificados e escolhidos deterministicamente."""

    runs = [json.loads(line) for line in V2_RUNS.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest = {run["sample_id"]: run for run in runs}
    measured = {
        sid
        for sid, run in latest.items()
        if not (run["errors"] and all(item["primary_layer"] == "PROVIDER" for item in run["errors"]))
    }
    by_class: dict[str, list[str]] = {}
    for sample in load_dev_split():
        if sample.sample_id in measured:
            by_class.setdefault(sample.target.request_class.value, []).append(sample.sample_id)
    for name in by_class:
        by_class[name].sort()

    chosen: list[str] = []
    while len(chosen) < EQUIVALENCE_SIZE:
        added = False
        for name in sorted(by_class):
            pool = [item for item in by_class[name] if item not in chosen]
            if pool and len(chosen) < EQUIVALENCE_SIZE:
                chosen.append(pool[0])
                added = True
        if not added:
            break
    return sorted(chosen), {name: len(items) for name, items in sorted(by_class.items())}


def run_smoke(provider) -> dict:
    results = []
    for label, message in SMOKE_FIXTURES:
        payload = UnderstandingInput(
            message=message,
            available_context=AvailableContext(
                tenant_ref="smoke_09_8", asset_refs=(), role="reliability_analyst", permissions=("read",)
            ),
        )
        record = _infer(provider, payload, f"smoke_{label}")
        output = record.get("output") or {}
        results.append(
            {
                "fixture": label,
                "message": message,
                "status": record["status"],
                "schema_valid": record["schema_valid"],
                "latency_ms": record["latency_ms"],
                "usage": record["usage"],
                "error": record["error"],
                "predicted_class": output.get("request_class"),
                "requested_actions": [item["capability"] for item in output.get("requested_actions", [])],
                "action_execution_allowed": (output.get("constraints") or {}).get("action_execution_allowed"),
                "entities": output.get("entities"),
                "missing_information": [item["field"] for item in output.get("missing_information", [])],
                "investigation_targets": output.get("investigation_targets"),
            }
        )
    # Timeout e 503 nao sao quebra de contrato: sao infraestrutura. Medir schema
    # sobre fixtures que nem chegaram a responder repetiria a confusao que o
    # projeto ja corrigiu para quota e para 5xx (Etapa 09.7B, §18).
    answered = [item for item in results if item["status"] == "success"]
    provider_failed = [item for item in results if item["status"] != "success"]
    valid = sum(item["schema_valid"] for item in answered)
    return {
        "fixtures": len(results),
        "answered": len(answered),
        "provider_failures": len(provider_failed),
        "provider_failure_fixtures": [item["fixture"] for item in provider_failed],
        "schema_valid": valid,
        "schema_invalid": len(answered) - valid,
        "schema_valid_rate_among_answered": round(valid / len(answered), 4) if answered else None,
        "action_execution_violations": sum(
            1 for item in answered if item["action_execution_allowed"] not in (False, None)
        ),
        "results": results,
    }


def run_equivalence(provider) -> dict:
    sample_ids, available = select_equivalence_cases()
    samples = {sample.sample_id: sample for sample in load_dev_split()}
    v2 = {
        run["sample_id"]: run
        for run in (json.loads(line) for line in V2_RUNS.read_text(encoding="utf-8").splitlines() if line.strip())
    }

    comparisons = []
    for sid in sample_ids:
        sample = samples[sid]
        gemini = _infer(provider, runtime_payload(sample), f"equiv_{sid}")
        groq = v2[sid]["components"].get("understanding") or {}
        groq_out = groq.get("output") or {}
        gem_out = gemini.get("output") or {}
        target = sample.target.request_class.value  # avaliação, depois da inferência

        comparisons.append(
            {
                "sample_id": sid,
                "target_class": target,
                "groq": {
                    "request_class": groq_out.get("request_class"),
                    "schema_valid": bool(groq.get("schema_valid")),
                    "latency_ms": groq.get("latency_ms"),
                    "usage": groq.get("usage"),
                    "entities": sorted(_identifiers(groq_out)),
                    "requested_actions": [i["capability"] for i in groq_out.get("requested_actions", [])],
                    "missing_information": [i["field"] for i in groq_out.get("missing_information", [])],
                    "investigation_targets": groq_out.get("investigation_targets"),
                },
                "gemini": {
                    "request_class": gem_out.get("request_class"),
                    "schema_valid": gemini["schema_valid"],
                    "latency_ms": gemini["latency_ms"],
                    "usage": gemini["usage"],
                    "error": gemini["error"],
                    "entities": sorted(_identifiers(gem_out)),
                    "requested_actions": [i["capability"] for i in gem_out.get("requested_actions", [])],
                    "missing_information": [i["field"] for i in gem_out.get("missing_information", [])],
                    "investigation_targets": gem_out.get("investigation_targets"),
                },
                "class_agreement": groq_out.get("request_class") == gem_out.get("request_class"),
                "groq_correct": groq_out.get("request_class") == target,
                "gemini_correct": gem_out.get("request_class") == target,
                "entities_preserved": _identifiers(gem_out) >= _identifiers(groq_out),
                "action_execution_allowed": (gem_out.get("constraints") or {}).get("action_execution_allowed"),
            }
        )

    total = len(comparisons) or 1
    return {
        "sample_ids": sample_ids,
        "classes_available_among_measured": available,
        "classes_absent_from_measured": [name for name in ("mixed", "unclear") if name not in available],
        "cases": len(comparisons),
        "gemini_schema_valid_rate": round(sum(c["gemini"]["schema_valid"] for c in comparisons) / total, 4),
        "class_agreement_rate": round(sum(c["class_agreement"] for c in comparisons) / total, 4),
        "groq_accuracy": round(sum(c["groq_correct"] for c in comparisons) / total, 4),
        "gemini_accuracy": round(sum(c["gemini_correct"] for c in comparisons) / total, 4),
        "entities_preserved_rate": round(sum(c["entities_preserved"] for c in comparisons) / total, 4),
        "action_execution_violations": sum(
            1 for c in comparisons if c["action_execution_allowed"] not in (False, None)
        ),
        "gemini_latency_ms_total": round(sum(c["gemini"]["latency_ms"] or 0 for c in comparisons), 3),
        "groq_latency_ms_total": round(sum(c["groq"]["latency_ms"] or 0 for c in comparisons), 3),
        "gemini_tokens": sum((c["gemini"]["usage"] or {}).get("total_tokens", 0) for c in comparisons),
        "groq_tokens": sum((c["groq"]["usage"] or {}).get("total_tokens", 0) for c in comparisons),
        "confusion_gemini": dict(
            Counter(f"{c['target_class']}->{c['gemini']['request_class']}" for c in comparisons)
        ),
        "comparisons": comparisons,
    }


def gate(smoke: dict, equivalence: dict | None) -> dict:
    """Critério do §8: equivalência funcional, nunca textual."""

    answered = smoke.get("answered", 0)
    checks = {
        # Validade de schema so e avaliada sobre o que o provider respondeu.
        "smoke_schema_valid": answered > 0 and smoke["schema_valid"] == answered,
        "smoke_no_action_violation": smoke["action_execution_violations"] == 0,
        # Exigir que a maioria das classes tenha sido exercitada de fato, para
        # que uma infraestrutura ruim nao aprove o gate por omissao.
        "smoke_coverage_sufficient": answered >= 4,
    }
    if equivalence:
        checks.update(
            {
                "equivalence_schema_valid": equivalence["gemini_schema_valid_rate"] == 1.0,
                "no_action_violation": equivalence["action_execution_violations"] == 0,
                "entities_preserved": equivalence["entities_preserved_rate"] >= 0.90,
                "no_severe_accuracy_regression": equivalence["gemini_accuracy"]
                >= equivalence["groq_accuracy"] - 0.20,
            }
        )
    approved = all(checks.values())
    return {
        "checks": checks,
        "verdict": "GEMINI_UNDERSTANDING_APPROVED" if approved else "GEMINI_UNDERSTANDING_NOT_APPROVED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida o Gemini como Understanding (Etapa 09.8).")
    parser.add_argument("--execute", action="store_true", help="Autoriza chamadas reais ao provider.")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--equivalence", action="store_true")
    args = parser.parse_args(argv)
    load_local_env(ROOT / "api" / ".env")

    if not args.execute:
        ids, available = select_equivalence_cases()
        print(
            json.dumps(
                {
                    "status": "READY",
                    "smoke_fixtures": len(SMOKE_FIXTURES),
                    "equivalence_sample_ids": ids,
                    "classes_available_among_measured": available,
                },
                ensure_ascii=False,
            )
        )
        return 0

    config = default_provider_configs()[ProviderName.GEMINI]
    provider = create_provider(config)
    try:
        smoke = (
            run_smoke(provider)
            if args.smoke
            else {"fixtures": 0, "schema_valid": 0, "schema_invalid": 0, "action_execution_violations": 0, "results": []}
        )
        equivalence = run_equivalence(provider) if args.equivalence else None
    finally:
        provider.close()

    verdict = gate(smoke, equivalence)
    payload = {
        "stage": "09.8",
        "understanding_model": config.model,
        "prompt_version": PROMPT_VERSION_V2,
        "smoke": smoke,
        "equivalence": equivalence,
        "gate": verdict,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "verdict": verdict["verdict"],
                "checks": verdict["checks"],
                "smoke_valid": f"{smoke['schema_valid']}/{smoke['fixtures']}",
            },
            ensure_ascii=False,
        )
    )
    return 0 if verdict["verdict"] == "GEMINI_UNDERSTANDING_APPROVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

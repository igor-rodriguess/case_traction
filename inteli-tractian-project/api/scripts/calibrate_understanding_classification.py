"""Calibração isolada da classificação do Understanding (Etapa 09.6, §13).

Mede apenas `request_class` sobre o split DEV autorizado, sem executar Planner,
Investigator ou tools. Isolar o componente torna a comparação com a Etapa 09.5
limpa: a única variável é o prompt.

As predições da V1 vêm do artefato já gravado, então a comparação não gasta
chamadas para reproduzir o que já foi medido.

Execução:
    python -m scripts.calibrate_understanding_classification            # plano
    python -m scripts.calibrate_understanding_classification --execute  # rodada
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from time import sleep
from uuid import uuid4

from pydantic import ValidationError

from app.agents.understanding.dataset import load_dev_split
from app.agents.understanding.prompts import PROMPT_VERSION_V2, SYSTEM_PROMPT_V2, build_user_prompt
from app.agents.understanding.schemas import RequestClass, UnderstandingOutput
from app.evaluation.dataset_validation import runtime_payload
from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, LLMResponseStatus, StructuredOutputMode
from app.llm.real_providers import ProviderName, create_provider, default_provider_configs
from scripts.diagnose_llm_providers import load_local_env


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "experiments" / "understanding-calibration-v2"
BASELINE_RUNS = ROOT / "experiments" / "e2e-full-dev-v1" / "runs.jsonl"
CLASSES: tuple[str, ...] = tuple(item.value for item in RequestClass)


def _request(payload: str) -> LLMRequest:
    return LLMRequest(
        request_id=f"calib_understanding_{uuid4().hex}",
        agent_role="understanding",
        messages=(LLMMessage(role="system", content=SYSTEM_PROMPT_V2), LLMMessage(role="user", content=payload)),
        prompt_version=PROMPT_VERSION_V2,
        generation=LLMGenerationParameters(temperature=0.0),
        expected_schema=UnderstandingOutput.model_json_schema(),
        structured_output_mode=StructuredOutputMode.JSON_SCHEMA,
        max_output_tokens=2048,
        timeout_seconds=45,
    )


def baseline_predictions() -> dict[str, str | None]:
    """Predições da V1 lidas do artefato; nenhuma chamada é refeita."""

    if not BASELINE_RUNS.exists():
        return {}
    predictions: dict[str, str | None] = {}
    for line in BASELINE_RUNS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        run = json.loads(line)
        output = (run.get("components", {}).get("understanding") or {}).get("output")
        predictions[run["sample_id"]] = output.get("request_class") if output else None
    return predictions


def score(pairs: list[tuple[str, str | None]]) -> dict[str, object]:
    """Acurácia global, por classe, recall e precisão a partir dos pares."""

    confusion = Counter(pairs)
    scored = [(expected, predicted) for expected, predicted in pairs if predicted is not None]
    per_class: dict[str, dict[str, object]] = {}
    for name in CLASSES:
        expected_total = sum(expected == name for expected, _ in pairs)
        predicted_total = sum(predicted == name for _, predicted in pairs)
        hits = sum(expected == predicted == name for expected, predicted in pairs)
        per_class[name] = {
            "support": expected_total,
            "predicted": predicted_total,
            "hits": hits,
            "recall": round(hits / expected_total, 4) if expected_total else None,
            "precision": round(hits / predicted_total, 4) if predicted_total else None,
        }
    return {
        "samples": len(pairs),
        "scored": len(scored),
        "unscored": len(pairs) - len(scored),
        "overall_accuracy": round(
            sum(expected == predicted for expected, predicted in scored) / len(scored), 4
        )
        if scored
        else None,
        "per_class": per_class,
        # `predicted` é None quando o caso não produziu saída válida; ordenar
        # pelo texto evita comparar None com str e preserva a entrada no laudo.
        "confusion": {
            f"{expected}->{predicted or 'SEM_SAIDA'}": count
            for (expected, predicted), count in sorted(
                confusion.items(), key=lambda item: (item[0][0], item[0][1] or "")
            )
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibração de classificação do Understanding.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--throttle-seconds", type=float, default=3.0)
    args = parser.parse_args(argv)

    load_local_env(ROOT / "api" / ".env")
    samples = load_dev_split()
    baseline = baseline_predictions()
    v1_pairs = [(sample.target.request_class.value, baseline.get(sample.sample_id)) for sample in samples]

    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "READY",
                    "prompt_version": PROMPT_VERSION_V2,
                    "samples": len(samples),
                    "v1_baseline": score(v1_pairs),
                },
                ensure_ascii=False,
            )
        )
        return 0

    configs = default_provider_configs()
    provider = create_provider(configs[ProviderName.GROQ])
    records: list[dict[str, object]] = []
    try:
        for index, sample in enumerate(samples):
            if index:
                sleep(args.throttle_seconds)
            response = provider.infer(_request(build_user_prompt(runtime_payload(sample))))
            predicted: str | None = None
            error: str | None = None
            if response.status is LLMResponseStatus.SUCCESS:
                try:
                    raw = json.loads(response.output) if isinstance(response.output, str) else response.output
                    predicted = UnderstandingOutput.model_validate(raw).request_class.value
                except (ValidationError, ValueError, TypeError) as exc:
                    error = type(exc).__name__
            else:
                error = response.error.code.value if response.error else "provider_failure"
            records.append(
                {
                    "sample_id": sample.sample_id,
                    "expected": sample.target.request_class.value,
                    "predicted": predicted,
                    "error": error,
                    "finish_reason": response.metadata.finish_reason,
                    "latency_ms": response.duration_ms,
                    "usage": response.usage.model_dump(mode="json") if response.usage else None,
                }
            )
            print(f"[{index + 1}/{len(samples)}] {sample.sample_id} esperado={records[-1]['expected']} previsto={predicted}")
    finally:
        provider.close()

    v2_pairs = [(item["expected"], item["predicted"]) for item in records]
    report = {
        "prompt_version_v1": "understanding_prompt_v1",
        "prompt_version_v2": PROMPT_VERSION_V2,
        "provider": "groq",
        "model": configs[ProviderName.GROQ].model,
        "v1": score(v1_pairs),
        "v2": score(v2_pairs),
        "records": records,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "calibration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "v1_accuracy": report["v1"]["overall_accuracy"],
                "v2_accuracy": report["v2"]["overall_accuracy"],
                "v1_execute_recall": report["v1"]["per_class"]["execute"]["recall"],
                "v2_execute_recall": report["v2"]["per_class"]["execute"]["recall"],
                "v1_mixed_precision": report["v1"]["per_class"]["mixed"]["precision"],
                "v2_mixed_precision": report["v2"]["per_class"]["mixed"]["precision"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

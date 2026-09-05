"""Showcase da Etapa 09.6 para revisão humana.

A Full DEV V2 não foi executada — a cota do provider esgotou —, então o showcase
reúne a evidência que existe: o reparo do teto de tokens verificado caso a caso,
a matriz de capacidade temporal, a calibração pareada do Understanding e o único
caso E2E que o smoke chegou a completar.

Declarar o que falta é parte do artefato: `full_dev_v2_executed` é `false`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.evaluation.tool_capabilities import build_matrix


ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "experiments" / "e2e-full-dev-v2-smoke"
CALIBRATION = ROOT / "experiments" / "understanding-calibration-v2" / "calibration.json"
V1_RUNS = ROOT / "experiments" / "e2e-full-dev-v1" / "runs.jsonl"
OUTPUT = ROOT / "docs" / "architecture" / "examples" / "09-6-full-dev-v2-showcase.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _paired_calibration() -> dict[str, Any]:
    """Compara V1 e V2 só onde ambos produziram saída, para não iludir a média."""

    calibration = _load(CALIBRATION)
    if not calibration or not V1_RUNS.exists():
        return {}
    v1: dict[str, str | None] = {}
    for line in V1_RUNS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            run = json.loads(line)
            output = (run.get("components", {}).get("understanding") or {}).get("output")
            v1[run["sample_id"]] = output.get("request_class") if output else None

    common = [
        item
        for item in calibration["records"]
        if item["predicted"] and v1.get(item["sample_id"]) is not None
    ]
    changes = [
        {
            "sample_id": item["sample_id"],
            "expected": item["expected"],
            "v1": v1[item["sample_id"]],
            "v2": item["predicted"],
            "verdict": (
                "improved"
                if item["predicted"] == item["expected"]
                else "regressed"
                if v1[item["sample_id"]] == item["expected"]
                else "lateral"
            ),
        }
        for item in common
        if v1[item["sample_id"]] != item["predicted"]
    ]
    return {
        "paired_cases": len(common),
        "accuracy_v1": round(sum(v1[i["sample_id"]] == i["expected"] for i in common) / len(common), 4),
        "accuracy_v2": round(sum(i["predicted"] == i["expected"] for i in common) / len(common), 4),
        "regressions": sum(item["verdict"] == "regressed" for item in changes),
        "changes": changes,
        "unscored_due_to_provider_quota": calibration["v2"]["unscored"],
    }


def main() -> int:
    matrix = build_matrix()
    smoke_runs = [
        json.loads(line)
        for line in (SMOKE / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if (SMOKE / "runs.jsonl").exists() else []
    completed = [run for run in smoke_runs if run["terminal_status"] != "FAILED"]

    payload = {
        "experiment_version": "e2e-full-dev-v2",
        "routing_version": "MODEL_ROUTING_V5",
        "routing_note": "Routing assignment unchanged. Version increment reflects configuration, prompt and capability changes.",
        "full_dev_v2_executed": False,
        "blocked_by": "PROVIDER_QUOTA_EXHAUSTED",
        "blocked_evidence": {
            "identical_v1_configuration_also_rejected": True,
            "detail": "Understanding com prompt v1 e orçamento 1800 recebeu HTTP 429 em 105 ms.",
        },
        "planner_token_repair": _load(SMOKE / "planner-token-repair.json"),
        "temporal_capability_matrix": {
            "any_tool_supports_temporal_filter": matrix.any_tool_supports_temporal_filter,
            "tools_returning_timestamped_data": list(matrix.tools_returning_timestamped_data),
            "tools": [
                {
                    "tool_name": item.tool_name,
                    "temporal_support": item.temporal_support.value,
                    "accepted_arguments": list(item.accepted_arguments),
                    "required_arguments": list(item.required_arguments),
                }
                for item in matrix.tools
            ],
        },
        "understanding_calibration": _paired_calibration(),
        "smoke": {
            "sample_ids_attempted": [run["sample_id"] for run in smoke_runs],
            "completed_cases": [
                {
                    "sample_id": run["sample_id"],
                    "terminal_status": run["terminal_status"],
                    "understanding_request_class": (
                        (run["components"].get("understanding") or {}).get("output") or {}
                    ).get("request_class"),
                    "temporal_policy": run["components"].get("temporal_policy"),
                    "investigator_decisions": [
                        {
                            "type": item["output"]["type"],
                            "reason_codes": item["output"]["reason_codes"],
                            "first_pass_valid": item["first_pass_valid"],
                            "completion_policy": item.get("completion_policy"),
                        }
                        for item in run["components"].get("investigator", [])
                    ],
                    "errors": run["errors"],
                }
                for run in completed
            ],
            "quota_blocked_cases": [
                run["sample_id"]
                for run in smoke_runs
                if any(error["code"] == "RATE_LIMIT" for error in run["errors"])
            ],
        },
        "pending_measurements": [
            "terminalidades e taxa de terminal válido da V2",
            "taxa de FAILED após os reparos",
            "validade de primeira passagem do Investigator com contrato informado",
            "taxas de ASK_USER e ESCALATE sob a política temporal",
            "tokens, latência e custo da V2",
            "se o Reporter é alcançado",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{OUTPUT} kb={OUTPUT.stat().st_size / 1024:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

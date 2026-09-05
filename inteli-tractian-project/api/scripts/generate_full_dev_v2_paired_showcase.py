"""Showcase pareado da Etapa 09.7 (§33).

Mostra cada caso medido na V2 ao lado do mesmo caso na V1, para que a leitura
seja comparação e não impressão. Categorias que a rodada parcial não alcançou
são listadas como ausentes, em vez de silenciadas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "experiments" / "e2e-full-dev-v1" / "runs.jsonl"
V2 = ROOT / "experiments" / "e2e-full-dev-v2" / "runs.jsonl"
CALIBRATION = ROOT / "experiments" / "understanding-calibration-v2" / "calibration.json"
REPAIR = ROOT / "experiments" / "e2e-full-dev-v2-smoke" / "planner-token-repair.json"
OUTPUT = ROOT / "docs" / "architecture" / "examples" / "09-7-full-dev-v2-showcase.json"

_TARGET_CATEGORIES = (
    "understanding_improvement",
    "execute_classified_correctly",
    "safe_temporal_handling",
    "safe_escalation",
    "awaiting_information",
    "real_error",
    "data_coverage_gap",
    "previously_truncated_planner",
)


def _runs(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return {
        json.loads(line)["sample_id"]: json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _side(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    understanding = (run["components"].get("understanding") or {}).get("output") or {}
    planner = run["components"].get("planner") or {}
    return {
        "terminal_status": run["terminal_status"],
        "failure_category": run.get("failure_category"),
        "request_class": understanding.get("request_class"),
        "requested_actions": [item["capability"] for item in understanding.get("requested_actions", [])],
        "planner": {
            "schema_valid": planner.get("schema_valid"),
            "finish_reason": planner.get("finish_reason"),
            "output_tokens": (planner.get("usage") or {}).get("output_tokens"),
        },
        "investigator_decisions": [
            {
                "type": item["output"]["type"],
                "reason_codes": item["output"]["reason_codes"],
                "first_pass_valid": item["first_pass_valid"],
                "policy_reason": (item.get("completion_policy") or {}).get("reason_code"),
                "tool": (item["output"].get("tool_request") or {}).get("tool_name"),
                "arguments": (item["output"].get("tool_request") or {}).get("arguments"),
            }
            for item in run["components"].get("investigator", [])
        ],
        "temporal_policy": run["components"].get("temporal_policy"),
        "tools_executed": [e["tool_name"] for e in run["trace"] if e["event_type"] == "tool_completed"],
        "evidence": [
            {"evidence_id": r["evidence_id"], "tool_name": r["tool_name"], "evidence_status": r["evidence_status"],
             "source_call_id": r["source_call_id"]}
            for r in run["evidence_ledger"]
        ],
        "trace_event_types": [e["event_type"] for e in run["trace"]],
        "errors": run["errors"],
        "duration_ms": run["duration_ms"],
    }


def _primary_failure_layer(v2: dict[str, Any]) -> str:
    coverage = v2.get("coverage") or {}
    if v2["errors"]:
        return v2["errors"][0]["primary_layer"]
    if coverage.get("alignment") in {"MISALIGNED", "IMPOSSIBLE_FROM_API"}:
        return "DATA"
    temporal = v2["components"].get("temporal_policy") or {}
    if temporal.get("reason_code", "").startswith("TEMPORAL"):
        return "TOOL"
    return "NONE"


def main() -> int:
    v1, v2 = _runs(V1), _runs(V2)
    measured = [
        sid for sid, run in v2.items() if not any(e["code"] == "RATE_LIMIT" for e in run["errors"])
    ]
    cases = {
        sid: {
            "request": v2[sid]["state"]["request"],
            "training_tags": v2[sid]["training_tags"],
            "coverage": v2[sid]["coverage"],
            "primary_failure_layer": _primary_failure_layer(v2[sid]),
            "v1": _side(v1.get(sid)),
            "v2": _side(v2[sid]),
        }
        for sid in measured
    }
    present = set()
    for sid, case in cases.items():
        if case["v2"]["terminal_status"] == "SAFE_ESCALATION":
            present.add("safe_escalation")
        if case["v2"]["terminal_status"] == "AWAITING_REQUIRED_INFORMATION":
            present.add("awaiting_information")
        if (case["v2"].get("temporal_policy") or {}).get("reason_code", "").startswith("TEMPORAL"):
            present.add("safe_temporal_handling")
        if "DATA_COVERAGE_WARNING" in case["coverage"]["warnings"]:
            present.add("data_coverage_gap")
        if case["v2"]["errors"]:
            present.add("real_error")
        if case["v1"] and case["v1"]["request_class"] != case["v2"]["request_class"]:
            present.add("understanding_improvement")
        if case["v2"]["request_class"] == "execute":
            present.add("execute_classified_correctly")

    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8")) if CALIBRATION.exists() else None
    payload = {
        "experiment_version": "e2e-full-dev-v2",
        "routing_version": "MODEL_ROUTING_V5",
        "run_status": "RUN_PAUSED_PROVIDER_QUOTA",
        "measured_cases": len(measured),
        "split_size": 60,
        "coverage_of_split": round(len(measured) / 60, 4),
        "categories_present": sorted(present),
        "categories_absent": [item for item in _TARGET_CATEGORIES if item not in present],
        "absent_because": "a rodada parou em 3 de 60 casos por esgotamento da cota diária do provider",
        "paired_cases": cases,
        "evidence_from_earlier_stages": {
            "planner_token_repair": json.loads(REPAIR.read_text(encoding="utf-8")) if REPAIR.exists() else None,
            "understanding_calibration_v1_v2": (
                {"v1": calibration["v1"]["per_class"], "v2": calibration["v2"]["per_class"]} if calibration else None
            ),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{OUTPUT.name} casos={len(measured)} presentes={sorted(present)} ausentes={payload['categories_absent']} kb={OUTPUT.stat().st_size/1024:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

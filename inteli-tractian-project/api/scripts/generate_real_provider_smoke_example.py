"""Gera showcase mock seguro; não lê .env e não chama providers."""

from __future__ import annotations

import json
from pathlib import Path

EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "examples" / "09-real-provider-smoke-example.json"

def build_showcase() -> dict[str, object]:
    return {"showcase_type": "mock_real_provider_smoke", "external_calls": 0, "credentials_present": False, "results": [{"provider": name, "model": "not_configured", "status": "not_configured", "latency_ms": 0.0, "usage": None, "schema_valid": None, "contract_valid": None, "error_category": "not_configured"} for name in ("groq", "gemini", "cerebras")]}

def write_showcase(path: Path = EXAMPLE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_showcase(), indent=2) + "\n", encoding="utf-8")
    return path

if __name__ == "__main__": print(write_showcase())

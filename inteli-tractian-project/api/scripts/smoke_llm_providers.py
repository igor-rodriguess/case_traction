"""Smoke manual: por padrão não chama rede; use --execute somente após autorização."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, create_provider, default_provider_configs


def load_local_env(path: Path) -> None:
    """Carrega chaves apenas para o ambiente do processo; nunca imprime valores."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        if name.strip() and value.strip():
            os.environ.setdefault(name.strip(), value.strip())


def smoke_request(provider: str) -> LLMRequest:
    return LLMRequest(request_id=f"smoke_{provider}", agent_role="connectivity_smoke", messages=(LLMMessage(role="user", content="Retorne exatamente um objeto JSON: {\"ok\": true}."),), prompt_version="smoke.v1", generation=LLMGenerationParameters(temperature=0), expected_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}, max_output_tokens=32, timeout_seconds=15)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Autoriza no máximo uma chamada por provider configurado.")
    args = parser.parse_args(argv)
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    for name, config in default_provider_configs().items():
        configured = bool(config.enabled and config.model and os.getenv(config.credential_env))
        if not args.execute or not configured:
            print(f"{name.value}: {'READY' if configured else 'NOT_CONFIGURED'}")
            continue
        provider = create_provider(config)
        try:
            response = provider.infer(smoke_request(name.value))
        finally:
            provider.close()
        error_category = response.error.code.value if response.error else "none"
        print(f"{name.value}: status={response.status.value} model={response.model} latency_ms={response.duration_ms} usage={'available' if response.usage else 'unavailable'} error_category={error_category}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

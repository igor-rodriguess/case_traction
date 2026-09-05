"""Diagnóstico manual e seguro; não é chamado por pytest, import ou startup."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.llm import CredentialStatus, LLMGenerationParameters, LLMMessage, LLMRequest
from app.llm.real_providers import create_provider, default_provider_configs, diagnostic_result
from scripts.smoke_llm_providers import load_local_env


RESULT_PATH = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "examples" / "09-1-provider-smoke-results.json"


def connectivity_request(provider: str) -> LLMRequest:
    """Pedido deliberadamente sem schema: mede apenas autenticação e conectividade."""
    return LLMRequest(
        request_id=f"diagnostic_connectivity_{provider}",
        agent_role="connectivity_diagnostic",
        messages=(LLMMessage(role="user", content="Return the exact short text: OK."),),
        prompt_version="connectivity.v1",
        generation=LLMGenerationParameters(temperature=0),
        expected_schema={},
        max_output_tokens=16,
        timeout_seconds=45,
    )


def credential_status(name: str) -> CredentialStatus:
    return CredentialStatus.CONFIGURED if os.getenv(name) else CredentialStatus.MISSING


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Autoriza no máximo uma chamada mínima por provider configurado.")
    parser.add_argument("--provider", action="append", choices=("groq", "gemini", "cerebras"), help="Restringe a execução aos providers informados.")
    parser.add_argument("--write-results", action="store_true", help="Grava somente diagnóstico sanitizado em docs/architecture/examples.")
    args = parser.parse_args(argv)
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    results = []
    for name, config in default_provider_configs().items():
        if args.provider and name.value not in args.provider:
            continue
        credential = credential_status(config.credential_env)
        if not args.execute or credential is not CredentialStatus.CONFIGURED or not config.enabled or not config.model:
            print(f"{name.value}: credential={credential.value} model={config.model or 'not_configured'} endpoint={config.base_url} timeout_s={config.timeout_seconds}")
            continue
        provider = create_provider(config)
        try:
            response = provider.infer(connectivity_request(name.value))
        finally:
            provider.close()
        result = diagnostic_result(response, credential)
        results.append(result.model_dump(mode="json"))
        print(f"{result.provider}: connectivity={result.connectivity_status.value} http_status={result.http_status or 'none'} error_category={result.error_category.value if result.error_category else 'none'} root_cause_layer={result.root_cause_layer.value} latency_ms={result.latency_ms}")
    if args.write_results:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(json.dumps({"result_type": "controlled_connectivity_diagnostic", "external_calls": len(results), "results": results}, indent=2) + "\n", encoding="utf-8")
        print(f"safe_results={RESULT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

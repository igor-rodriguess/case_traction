"""Adapters reais testados só com MockTransport: nunca rede ou credencial real."""

from __future__ import annotations

import json

import httpx
import pytest

from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest
from app.llm.real_providers import ProviderConfig, ProviderName, RetryPolicy, create_provider, default_provider_configs


def request() -> LLMRequest:
    return LLMRequest(request_id="request_provider", agent_role="smoke", messages=(LLMMessage(role="user", content="JSON."),), prompt_version="smoke.v1", generation=LLMGenerationParameters(), expected_schema={"type": "object"}, max_output_tokens=32, timeout_seconds=5)


def config(name: ProviderName) -> ProviderConfig:
    return ProviderConfig(provider=name, model="model-confirmed-by-user", base_url="https://provider.test/v1", credential_env="TEST_PROVIDER_KEY", enabled=True, retry=RetryPolicy(max_attempts=2))


@pytest.mark.parametrize("name", [ProviderName.GROQ, ProviderName.CEREBRAS])
def test_openai_compatible_adapters_normalize_success_and_usage(monkeypatch, name) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["response_format"]["type"] == "json_schema"
        assert req.headers["authorization"] == "Bearer test-only"
        return httpx.Response(200, json={"id": "provider_response", "model": "returned-model", "choices": [{"message": {"content": "{\"ok\": true}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})
    provider = create_provider(config(name), transport=httpx.MockTransport(handler))
    result = provider.infer(request())
    assert result.status.value == "success" and result.usage is not None and result.usage.total_tokens == 5
    provider.close()


def test_gemini_normalizes_success_and_usage(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(200, json={"responseId": "gemini_response", "candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}, "finishReason": "STOP"}], "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5}})
    provider = create_provider(config(ProviderName.GEMINI), transport=httpx.MockTransport(handler))
    assert provider.infer(request()).usage is not None
    provider.close()


@pytest.mark.parametrize("status, expected", [(401, "authentication"), (429, "rate_limit"), (500, "http_status")])
def test_errors_are_safe_and_retry_only_transient(monkeypatch, status, expected) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-never-exposed")
    calls = 0
    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls; calls += 1
        return httpx.Response(status, json={"error": {"message": "secret-never-exposed"}})
    provider = create_provider(config(ProviderName.GROQ), transport=httpx.MockTransport(handler))
    result = provider.infer(request())
    assert result.error is not None and result.error.code.value == expected
    assert "secret" not in result.error.message
    assert calls == (2 if status in {429, 500} else 1)
    provider.close()


def test_missing_credentials_is_not_configured_and_never_calls_network(monkeypatch) -> None:
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    provider = create_provider(config(ProviderName.GROQ), transport=httpx.MockTransport(lambda _: pytest.fail("network must not be called")))
    result = provider.infer(request())
    assert result.error is not None and result.error.code.value == "not_configured"
    provider.close()


def test_usage_absent_stays_unknown(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    provider = create_provider(config(ProviderName.CEREBRAS), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})))
    assert provider.infer(request()).usage is None
    provider.close()


def test_initial_role_models_are_read_without_overriding_generic_configuration(monkeypatch) -> None:
    for name in ("GROQ_MODEL", "GEMINI_MODEL", "CEREBRAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_INVESTIGATOR_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GEMINI_UNDERSTANDING_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("CEREBRAS_REPORTER_MODEL", "gpt-oss-120b")
    configs = default_provider_configs()
    assert configs[ProviderName.GROQ].model == "openai/gpt-oss-120b"
    assert configs[ProviderName.GEMINI].model == "gemini-3.5-flash-lite"
    assert configs[ProviderName.CEREBRAS].model == "gpt-oss-120b"
    monkeypatch.setenv("GEMINI_MODEL", "generic-gemini-model")
    assert default_provider_configs()[ProviderName.GEMINI].model == "generic-gemini-model"

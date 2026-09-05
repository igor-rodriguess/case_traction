"""Adapters reais testados só com MockTransport: nunca rede ou credencial real."""

from __future__ import annotations

import json

import httpx
import pytest

from app.llm import LLMGenerationParameters, LLMMessage, LLMRequest, StructuredOutputMode
from app.llm.contracts import CredentialStatus
from app.llm.real_providers import ProviderConfig, ProviderName, RetryPolicy, create_provider, default_provider_configs, diagnostic_result


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
        assert body["response_format"]["json_schema"]["strict"] is False
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
    assert provider.last_raw_response_sanitized is not None
    assert provider.last_raw_response_sanitized["candidates"][0]["content"]["parts"][0]["text"] == "{\"ok\": true}"
    provider.close()


def test_provider_raw_diagnostic_redacts_secret_fields(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    payload = {"responseId": "safe-id", "secret": "must-not-survive", "candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
    provider = create_provider(config(ProviderName.GEMINI), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    provider.infer(request())
    assert provider.last_raw_response_sanitized is not None
    assert provider.last_raw_response_sanitized["secret"] == "[REDACTED]"
    provider.close()


def test_gemini_sends_exact_schema_and_preserves_structured_text(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    structured = '{"type":"ask_user","tool_request":null,"required_information":["asset_id"]}'
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["generationConfig"]["responseJsonSchema"] == {"type": "object"}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": structured}]}}]})
    provider = create_provider(config(ProviderName.GEMINI), transport=httpx.MockTransport(handler))
    response = provider.infer(request())
    assert response.output == structured
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


def test_groq_allows_component_request_up_to_its_explicit_ceiling(monkeypatch) -> None:
    for name in ("GROQ_MODEL", "GEMINI_MODEL", "CEREBRAS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_INVESTIGATOR_MODEL", "openai/gpt-oss-120b")
    assert default_provider_configs()[ProviderName.GROQ].max_output_tokens == 2048


@pytest.mark.parametrize("status, expected", [(400, "request_schema_error"), (402, "quota_exceeded"), (404, "model_not_found")])
def test_http_diagnostics_preserve_only_status_and_safe_category(monkeypatch, status, expected) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    provider = create_provider(config(ProviderName.GROQ), transport=httpx.MockTransport(lambda _: httpx.Response(status, json={"error": {"message": "private provider detail"}})))
    response = provider.infer(request())
    result = diagnostic_result(response, CredentialStatus.CONFIGURED)
    assert response.error is not None and response.error.http_status == status
    assert result.error_category is not None and result.error_category.value == expected
    assert "private" not in result.message_sanitized
    provider.close()


@pytest.mark.parametrize("name", [ProviderName.GROQ, ProviderName.CEREBRAS, ProviderName.GEMINI])
def test_plain_connectivity_request_omits_structured_output(monkeypatch, name) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if name is ProviderName.GEMINI:
            assert "responseMimeType" not in body["generationConfig"]
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})
        assert "response_format" not in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    provider = create_provider(config(name), transport=httpx.MockTransport(handler))
    plain = LLMRequest(request_id="plain", agent_role="connectivity", messages=(LLMMessage(role="user", content="OK"),), prompt_version="connectivity.v1", generation=LLMGenerationParameters(), expected_schema={}, max_output_tokens=16, timeout_seconds=5)
    assert provider.infer(plain).status.value == "success"
    provider.close()


def test_json_object_mode_uses_native_json_without_schema(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["reasoning_format"] == "hidden"
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
    provider = create_provider(config(ProviderName.GROQ), transport=httpx.MockTransport(handler))
    value = LLMRequest(request_id="json_object", agent_role="reporter", messages=(LLMMessage(role="user", content="JSON"),), prompt_version="reporter.v3", generation=LLMGenerationParameters(), expected_schema={"type": "object"}, structured_output_mode=StructuredOutputMode.JSON_OBJECT, max_output_tokens=16, timeout_seconds=5)
    assert provider.infer(value).status.value == "success"
    provider.close()


def test_bad_request_reason_is_allowlisted_without_exposing_provider_body(monkeypatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "test-only")
    provider = create_provider(config(ProviderName.GROQ), transport=httpx.MockTransport(lambda _: httpx.Response(400, json={"error": {"message": "reasoning_format is invalid; secret detail must not leak"}})))
    result = provider.infer(request())
    assert result.error is not None
    assert result.error.message == "Provider recusou a configuração de reasoning format."
    assert "secret" not in result.error.message
    provider.close()

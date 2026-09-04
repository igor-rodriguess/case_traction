"""Adapters HTTP reais isolados atrás do contrato ``LLMProvider``.

Não há SDK, fallback ou chamada no import. Chaves nunca entram nos contratos.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.llm.contracts import LLMError, LLMErrorCode, LLMMetadata, LLMRequest, LLMResponse, LLMResponseStatus, LLMUsage


class ProviderName(str, Enum):
    GROQ = "groq"
    GEMINI = "gemini"
    CEREBRAS = "cerebras"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_attempts: int = Field(default=1, ge=1, le=3)


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    structured_output: bool | None = None
    tool_calling: bool | None = None
    usage_reporting: bool | None = None
    streaming: bool | None = None
    context_limit: int | None = Field(default=None, ge=1)
    model_listing: bool | None = None


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: ProviderName
    model: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: str
    timeout_seconds: float = Field(default=15, gt=0, le=120)
    max_output_tokens: int = Field(default=512, ge=1, le=32768)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    enabled: bool = False
    credential_env: str
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)


def default_provider_configs() -> dict[ProviderName, ProviderConfig]:
    """Nenhum modelo é presumido; o usuário o define no ambiente antes do smoke."""
    groq_model = os.getenv("GROQ_MODEL") or os.getenv("GROQ_INVESTIGATOR_MODEL")
    gemini_model = os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_UNDERSTANDING_MODEL")
    cerebras_model = os.getenv("CEREBRAS_MODEL") or os.getenv("CEREBRAS_REPORTER_MODEL")
    return {
        ProviderName.GROQ: ProviderConfig(provider=ProviderName.GROQ, base_url="https://api.groq.com/openai/v1", credential_env="GROQ_API_KEY", model=groq_model, enabled=bool(groq_model), capabilities=ProviderCapabilities(structured_output=None, tool_calling=True, usage_reporting=True, streaming=True, model_listing=True)),
        ProviderName.GEMINI: ProviderConfig(provider=ProviderName.GEMINI, base_url="https://generativelanguage.googleapis.com/v1beta", credential_env="GEMINI_API_KEY", model=gemini_model, enabled=bool(gemini_model), capabilities=ProviderCapabilities(structured_output=True, tool_calling=True, usage_reporting=True, streaming=True, model_listing=True)),
        ProviderName.CEREBRAS: ProviderConfig(provider=ProviderName.CEREBRAS, base_url="https://api.cerebras.ai/v1", credential_env="CEREBRAS_API_KEY", model=cerebras_model, enabled=bool(cerebras_model), capabilities=ProviderCapabilities(structured_output=None, tool_calling=True, usage_reporting=True, streaming=True, model_listing=True)),
    }


class BaseHTTPProvider:
    def __init__(self, config: ProviderConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._http = httpx.Client(base_url=config.base_url.rstrip("/"), timeout=config.timeout_seconds, transport=transport)

    def close(self) -> None:
        self._http.close()

    def infer(self, request: LLMRequest) -> LLMResponse:
        key = os.getenv(self.config.credential_env)
        if not self.config.enabled or not self.config.model or not key:
            return self._failure(request, LLMErrorCode.NOT_CONFIGURED, "Provider não configurado localmente.", False, 0.0, 1)
        started = perf_counter()
        for attempt in range(1, self.config.retry.max_attempts + 1):
            try:
                response = self._send(request, key)
            except httpx.TimeoutException:
                if attempt < self.config.retry.max_attempts:
                    continue
                return self._failure(request, LLMErrorCode.TIMEOUT, "Timeout do provider.", True, self._duration(started), attempt)
            except httpx.RequestError:
                if attempt < self.config.retry.max_attempts:
                    continue
                return self._failure(request, LLMErrorCode.PROVIDER_FAILURE, "Falha de conectividade do provider.", True, self._duration(started), attempt)
            if response.status_code in {429} or response.status_code >= 500:
                if attempt < self.config.retry.max_attempts:
                    continue
                code = LLMErrorCode.RATE_LIMIT if response.status_code == 429 else LLMErrorCode.HTTP_STATUS
                return self._failure(request, code, "Provider limitou ou falhou temporariamente.", True, self._duration(started), attempt)
            if response.status_code in {401, 403}:
                return self._failure(request, LLMErrorCode.AUTHENTICATION, "Autenticação do provider recusada.", False, self._duration(started), attempt)
            if not response.is_success:
                return self._failure(request, LLMErrorCode.HTTP_STATUS, "Provider retornou status não aceito.", False, self._duration(started), attempt)
            try:
                return self._normalize(request, response.json(), self._duration(started), attempt)
            except (ValueError, TypeError):
                return self._failure(request, LLMErrorCode.INVALID_JSON, "Provider retornou JSON inválido ou incompleto.", False, self._duration(started), attempt)
        raise AssertionError("Loop de retry deve retornar antes.")

    def _failure(self, request: LLMRequest, code: LLMErrorCode, message: str, retryable: bool, duration: float, attempts: int) -> LLMResponse:
        return LLMResponse(request_id=request.request_id, provider=self.config.provider.value, model=self.config.model or "not_configured", status=LLMResponseStatus.TIMEOUT if code is LLMErrorCode.TIMEOUT else LLMResponseStatus.PROVIDER_FAILURE, duration_ms=duration, error=LLMError(code=code, message=message, retryable=retryable), metadata=LLMMetadata(prompt_version=request.prompt_version, attempt_count=attempts))

    @staticmethod
    def _duration(started: float) -> float:
        return round((perf_counter() - started) * 1000, 3)

    def _send(self, request: LLMRequest, key: str) -> httpx.Response: raise NotImplementedError
    def _normalize(self, request: LLMRequest, payload: dict[str, Any], duration: float, attempts: int) -> LLMResponse: raise NotImplementedError


class _OpenAICompatibleProvider(BaseHTTPProvider):
    def _send(self, request: LLMRequest, key: str) -> httpx.Response:
        body: dict[str, Any] = {"model": self.config.model, "messages": [{"role": item.role.value, "content": item.content} for item in request.messages], "max_completion_tokens": min(request.max_output_tokens, self.config.max_output_tokens), "temperature": request.generation.temperature}
        if request.generation.top_p is not None: body["top_p"] = request.generation.top_p
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "canonical_output", "strict": True, "schema": request.expected_schema}}
        return self._http.post("/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)

    def _normalize(self, request: LLMRequest, payload: dict[str, Any], duration: float, attempts: int) -> LLMResponse:
        choice = payload["choices"][0]
        content = choice["message"]["content"]
        usage_data = payload.get("usage")
        keys = {"prompt_tokens", "completion_tokens", "total_tokens"}
        usage = None if not isinstance(usage_data, dict) or not keys <= set(usage_data) else LLMUsage(input_tokens=int(usage_data["prompt_tokens"]), output_tokens=int(usage_data["completion_tokens"]), total_tokens=int(usage_data["total_tokens"]))
        return LLMResponse(request_id=request.request_id, response_id=str(payload.get("id")) if payload.get("id") else None, provider=self.config.provider.value, model=str(payload.get("model") or self.config.model), status=LLMResponseStatus.SUCCESS, output=content, usage=usage, duration_ms=duration, metadata=LLMMetadata(prompt_version=request.prompt_version, finish_reason=choice.get("finish_reason"), attempt_count=attempts))


class GroqProvider(_OpenAICompatibleProvider): pass
class CerebrasProvider(_OpenAICompatibleProvider): pass


class GeminiProvider(BaseHTTPProvider):
    def _send(self, request: LLMRequest, key: str) -> httpx.Response:
        contents = [{"role": "user" if item.role.value != "assistant" else "model", "parts": [{"text": item.content}]} for item in request.messages]
        generation: dict[str, Any] = {"maxOutputTokens": min(request.max_output_tokens, self.config.max_output_tokens), "temperature": request.generation.temperature, "responseMimeType": "application/json", "responseJsonSchema": request.expected_schema}
        if request.generation.top_p is not None: generation["topP"] = request.generation.top_p
        return self._http.post(f"/models/{self.config.model}:generateContent", headers={"x-goog-api-key": key}, json={"contents": contents, "generationConfig": generation})

    def _normalize(self, request: LLMRequest, payload: dict[str, Any], duration: float, attempts: int) -> LLMResponse:
        candidate = payload["candidates"][0]
        content = candidate["content"]["parts"][0]["text"]
        usage_data = payload.get("usageMetadata")
        keys = {"promptTokenCount", "candidatesTokenCount", "totalTokenCount"}
        usage = None if not isinstance(usage_data, dict) or not keys <= set(usage_data) else LLMUsage(input_tokens=int(usage_data["promptTokenCount"]), output_tokens=int(usage_data["candidatesTokenCount"]), total_tokens=int(usage_data["totalTokenCount"]))
        return LLMResponse(request_id=request.request_id, response_id=str(payload.get("responseId")) if payload.get("responseId") else None, provider=self.config.provider.value, model=self.config.model or "not_configured", status=LLMResponseStatus.SUCCESS, output=content, usage=usage, duration_ms=duration, metadata=LLMMetadata(prompt_version=request.prompt_version, finish_reason=candidate.get("finishReason"), attempt_count=attempts))


def create_provider(config: ProviderConfig, *, transport: httpx.BaseTransport | None = None) -> BaseHTTPProvider:
    return {ProviderName.GROQ: GroqProvider, ProviderName.GEMINI: GeminiProvider, ProviderName.CEREBRAS: CerebrasProvider}[config.provider](config, transport=transport)

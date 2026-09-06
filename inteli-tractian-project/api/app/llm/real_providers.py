"""Adapters HTTP reais isolados atrás do contrato ``LLMProvider``.

Não há SDK, fallback ou chamada no import. Chaves nunca entram nos contratos.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from enum import Enum
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.llm.contracts import CredentialStatus, ConnectivityStatus, LLMError, LLMErrorCode, LLMMetadata, LLMRequest, LLMResponse, LLMResponseStatus, LLMUsage, ProviderDiagnosticResult, RootCauseLayer, StructuredOutputMode


class ProviderName(str, Enum):
    GROQ = "groq"
    GEMINI = "gemini"
    CEREBRAS = "cerebras"


class RetryPolicy(BaseModel):
    """Tentativas e espera entre elas.

    Um HTTP 503 significa "sobrecarregado": repetir no mesmo instante gasta a
    tentativa contra a condição que acabou de falhar. O backoff existe para que
    a segunda tentativa encontre um estado diferente do provider.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_attempts: int = Field(default=1, ge=1, le=3)
    backoff_seconds: float = Field(default=0.0, ge=0.0, le=30.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=4.0)

    def delay_before(self, next_attempt: int) -> float:
        """Espera antes da tentativa `next_attempt` (2 é a primeira repetição)."""

        if self.backoff_seconds <= 0 or next_attempt < 2:
            return 0.0
        return round(self.backoff_seconds * (self.backoff_multiplier ** (next_attempt - 2)), 3)


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
    strict_structured_output: bool = False
    credential_env: str
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)


def default_provider_configs() -> dict[ProviderName, ProviderConfig]:
    """Nenhum modelo é presumido; o usuário o define no ambiente antes do smoke."""
    groq_model = os.getenv("GROQ_MODEL") or os.getenv("GROQ_INVESTIGATOR_MODEL")
    gemini_model = os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_UNDERSTANDING_MODEL")
    cerebras_model = os.getenv("CEREBRAS_MODEL") or os.getenv("CEREBRAS_REPORTER_MODEL")
    return {
        ProviderName.GROQ: ProviderConfig(provider=ProviderName.GROQ, base_url="https://api.groq.com/openai/v1", credential_env="GROQ_API_KEY", model=groq_model, max_output_tokens=2048, enabled=bool(groq_model), capabilities=ProviderCapabilities(structured_output=None, tool_calling=True, usage_reporting=True, streaming=True, model_listing=True)),
        ProviderName.GEMINI: ProviderConfig(provider=ProviderName.GEMINI, base_url="https://generativelanguage.googleapis.com/v1beta", credential_env="GEMINI_API_KEY", model=gemini_model, timeout_seconds=45, max_output_tokens=8192, retry=RetryPolicy(max_attempts=2, backoff_seconds=2.0), enabled=bool(gemini_model), capabilities=ProviderCapabilities(structured_output=True, tool_calling=True, usage_reporting=True, streaming=True, model_listing=True)),
        ProviderName.CEREBRAS: ProviderConfig(provider=ProviderName.CEREBRAS, base_url="https://api.cerebras.ai/v1", credential_env="CEREBRAS_API_KEY", model=cerebras_model, enabled=bool(cerebras_model), capabilities=ProviderCapabilities(structured_output=None, tool_calling=True, usage_reporting=True, streaming=True, model_listing=True)),
    }


class BaseHTTPProvider:
    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._http = httpx.Client(base_url=config.base_url.rstrip("/"), timeout=config.timeout_seconds, transport=transport)
        self._last_raw_response_sanitized: dict[str, Any] | None = None
        self._sleep = sleeper
        self.retry_delays_observed: list[float] = []

    def _wait_before_retry(self, next_attempt: int) -> None:
        delay = self.config.retry.delay_before(next_attempt)
        self.retry_delays_observed.append(delay)
        if delay:
            self._sleep(delay)

    @property
    def last_raw_response_sanitized(self) -> dict[str, Any] | None:
        """Último envelope do provider sem headers, credenciais ou campos secretos."""
        return self._last_raw_response_sanitized

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
                    self._wait_before_retry(attempt + 1)
                    continue
                return self._failure(request, LLMErrorCode.TIMEOUT, "Timeout do provider.", True, self._duration(started), attempt)
            except httpx.RequestError:
                if attempt < self.config.retry.max_attempts:
                    self._wait_before_retry(attempt + 1)
                    continue
                return self._failure(request, LLMErrorCode.NETWORK_ERROR, "Falha de conectividade do provider.", True, self._duration(started), attempt)
            if response.status_code in {429} or response.status_code >= 500:
                if attempt < self.config.retry.max_attempts:
                    self._wait_before_retry(attempt + 1)
                    continue
                code = LLMErrorCode.RATE_LIMIT if response.status_code == 429 else LLMErrorCode.HTTP_STATUS
                return self._failure(request, code, "Provider limitou ou falhou temporariamente.", True, self._duration(started), attempt, response.status_code)
            if response.status_code in {401, 403}:
                return self._failure(request, LLMErrorCode.AUTHENTICATION, "Autenticação do provider recusada.", False, self._duration(started), attempt, response.status_code)
            if response.status_code == 404:
                return self._failure(request, LLMErrorCode.MODEL_NOT_FOUND, "Endpoint ou modelo não encontrado pelo provider.", False, self._duration(started), attempt, response.status_code)
            if response.status_code == 402:
                return self._failure(request, LLMErrorCode.QUOTA_EXCEEDED, "Quota do provider indisponível.", False, self._duration(started), attempt, response.status_code)
            if response.status_code == 400:
                return self._failure(request, LLMErrorCode.REQUEST_SCHEMA_ERROR, self._safe_bad_request_message(response), False, self._duration(started), attempt, response.status_code)
            if not response.is_success:
                return self._failure(request, LLMErrorCode.HTTP_STATUS, "Provider retornou status não aceito.", False, self._duration(started), attempt, response.status_code)
            try:
                payload = response.json()
                self._last_raw_response_sanitized = _sanitize_provider_payload(payload)
                return self._normalize(request, payload, self._duration(started), attempt)
            except (ValueError, TypeError, KeyError, IndexError):
                return self._failure(request, LLMErrorCode.RESPONSE_SCHEMA_ERROR, "Provider retornou resposta inválida ou incompleta.", False, self._duration(started), attempt, response.status_code)
        raise AssertionError("Loop de retry deve retornar antes.")

    def _truncation(self, request: LLMRequest, finish_reason: object, duration: float, attempts: int) -> LLMResponse | None:
        """Saída cortada pelo teto de tokens não é JSON inválido, é orçamento curto.

        Sem esta checagem o corte chega às camadas de cima disfarçado de erro de
        schema, e o diagnóstico aponta para o prompt em vez do limite. Repetir a
        mesma requisição com o mesmo teto daria o mesmo corte: não é retryable.
        """

        structured = bool(request.expected_schema) and request.structured_output_mode in {
            StructuredOutputMode.JSON_SCHEMA,
            StructuredOutputMode.JSON_OBJECT,
        }
        if not structured or str(finish_reason or "").lower() not in _TRUNCATION_MARKERS:
            return None
        return self._failure(
            request,
            LLMErrorCode.OUTPUT_TRUNCATED,
            "Saída truncada pelo limite de tokens antes de completar o JSON.",
            False,
            duration,
            attempts,
        )

    def _failure(self, request: LLMRequest, code: LLMErrorCode, message: str, retryable: bool, duration: float, attempts: int, http_status: int | None = None) -> LLMResponse:
        return LLMResponse(request_id=request.request_id, provider=self.config.provider.value, model=self.config.model or "not_configured", status=LLMResponseStatus.TIMEOUT if code is LLMErrorCode.TIMEOUT else LLMResponseStatus.PROVIDER_FAILURE, duration_ms=duration, error=LLMError(code=code, message=message, retryable=retryable, http_status=http_status), metadata=LLMMetadata(prompt_version=request.prompt_version, attempt_count=attempts))

    @staticmethod
    def _duration(started: float) -> float:
        return round((perf_counter() - started) * 1000, 3)

    @staticmethod
    def _safe_bad_request_message(response: httpx.Response) -> str:
        """Classifica 400 sem reter corpo, IDs, headers ou texto do provider."""
        try:
            error = response.json().get("error", {})
            raw = " ".join(str(error.get(key, "")) for key in ("code", "type", "message")).lower()
        except (ValueError, AttributeError):
            raw = ""
        categories = (
            ("reasoning_format", "Provider recusou a configuração de reasoning format."),
            ("response_format", "Provider recusou a configuração de response format."),
            ("json_schema", "Provider recusou o JSON Schema enviado."),
            ("json object", "Provider recusou o modo JSON Object."),
            ("message", "Provider recusou a estrutura de mensagens."),
            ("max_completion_tokens", "Provider recusou o limite de tokens de saída."),
        )
        for marker, safe_message in categories:
            if marker in raw:
                return safe_message
        return "Provider recusou o formato da requisição."

    def _send(self, request: LLMRequest, key: str) -> httpx.Response: raise NotImplementedError
    def _normalize(self, request: LLMRequest, payload: dict[str, Any], duration: float, attempts: int) -> LLMResponse: raise NotImplementedError


_SECRET_KEYS = frozenset({"api_key", "apikey", "authorization", "credential", "password", "secret", "x-goog-api-key"})

_TRUNCATION_MARKERS = frozenset({"length", "max_tokens"})
"""`finish_reason` de corte por orçamento: `length` na API OpenAI, `MAX_TOKENS` na Gemini."""


def _sanitize_provider_payload(value: Any, *, key: str | None = None) -> Any:
    """Cópia determinística do payload; nunca inclui request headers ou segredos conhecidos."""
    if key and key.lower() in _SECRET_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _sanitize_provider_payload(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_provider_payload(item) for item in value]
    if isinstance(value, str):
        return value[:30_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


class _OpenAICompatibleProvider(BaseHTTPProvider):
    def _send(self, request: LLMRequest, key: str) -> httpx.Response:
        body: dict[str, Any] = {"model": self.config.model, "messages": [{"role": item.role.value, "content": item.content} for item in request.messages], "max_completion_tokens": min(request.max_output_tokens, self.config.max_output_tokens), "temperature": request.generation.temperature}
        if request.generation.top_p is not None: body["top_p"] = request.generation.top_p
        if request.structured_output_mode is StructuredOutputMode.JSON_SCHEMA and request.expected_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "canonical_output", "strict": self.config.strict_structured_output, "schema": request.expected_schema}}
        elif request.structured_output_mode is StructuredOutputMode.JSON_OBJECT:
            body["response_format"] = {"type": "json_object"}
            if self.config.provider is ProviderName.GROQ:
                body["reasoning_format"] = "hidden"
        return self._http.post("/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)

    def _normalize(self, request: LLMRequest, payload: dict[str, Any], duration: float, attempts: int) -> LLMResponse:
        choice = payload["choices"][0]
        truncated = self._truncation(request, choice.get("finish_reason"), duration, attempts)
        if truncated is not None:
            return truncated
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
        generation: dict[str, Any] = {"maxOutputTokens": min(request.max_output_tokens, self.config.max_output_tokens), "temperature": request.generation.temperature}
        if request.expected_schema and request.structured_output_mode in {StructuredOutputMode.JSON_SCHEMA, StructuredOutputMode.JSON_OBJECT}:
            generation["responseMimeType"] = "application/json"
        if request.structured_output_mode is StructuredOutputMode.JSON_SCHEMA and request.expected_schema:
            generation.update({"responseMimeType": "application/json", "responseJsonSchema": request.expected_schema})
        if request.generation.top_p is not None: generation["topP"] = request.generation.top_p
        return self._http.post(f"/models/{self.config.model}:generateContent", headers={"x-goog-api-key": key}, json={"contents": contents, "generationConfig": generation})

    def _normalize(self, request: LLMRequest, payload: dict[str, Any], duration: float, attempts: int) -> LLMResponse:
        candidate = payload["candidates"][0]
        truncated = self._truncation(request, candidate.get("finishReason"), duration, attempts)
        if truncated is not None:
            return truncated
        content = candidate["content"]["parts"][0]["text"]
        usage_data = payload.get("usageMetadata")
        keys = {"promptTokenCount", "candidatesTokenCount", "totalTokenCount"}
        usage = None if not isinstance(usage_data, dict) or not keys <= set(usage_data) else LLMUsage(input_tokens=int(usage_data["promptTokenCount"]), output_tokens=int(usage_data["candidatesTokenCount"]), total_tokens=int(usage_data["totalTokenCount"]))
        return LLMResponse(request_id=request.request_id, response_id=str(payload.get("responseId")) if payload.get("responseId") else None, provider=self.config.provider.value, model=self.config.model or "not_configured", status=LLMResponseStatus.SUCCESS, output=content, usage=usage, duration_ms=duration, metadata=LLMMetadata(prompt_version=request.prompt_version, finish_reason=candidate.get("finishReason"), attempt_count=attempts))


def create_provider(
    config: ProviderConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> BaseHTTPProvider:
    return {ProviderName.GROQ: GroqProvider, ProviderName.GEMINI: GeminiProvider, ProviderName.CEREBRAS: CerebrasProvider}[
        config.provider
    ](config, transport=transport, sleeper=sleeper)


def diagnostic_result(response: LLMResponse, credential_status: CredentialStatus) -> ProviderDiagnosticResult:
    """Converte uma resposta canônica em diagnóstico seguro e persistível."""
    if response.status is LLMResponseStatus.SUCCESS:
        return ProviderDiagnosticResult(provider=response.provider, model=response.model, credential_status=credential_status, connectivity_status=ConnectivityStatus.SUCCESS, root_cause_layer=RootCauseLayer.UNKNOWN, latency_ms=response.duration_ms, usage=response.usage, message_sanitized="Conectividade confirmada.")
    error = response.error
    assert error is not None
    layer = RootCauseLayer.UNKNOWN
    if error.code in {LLMErrorCode.NOT_CONFIGURED, LLMErrorCode.AUTHENTICATION, LLMErrorCode.MODEL_NOT_FOUND, LLMErrorCode.QUOTA_EXCEEDED, LLMErrorCode.OUTPUT_TRUNCATED}:
        layer = RootCauseLayer.CONFIGURATION
    elif error.code in {LLMErrorCode.NETWORK_ERROR, LLMErrorCode.TIMEOUT}:
        layer = RootCauseLayer.NETWORK
    elif error.code in {LLMErrorCode.REQUEST_SCHEMA_ERROR, LLMErrorCode.RESPONSE_SCHEMA_ERROR, LLMErrorCode.INVALID_JSON, LLMErrorCode.INVALID_SCHEMA}:
        layer = RootCauseLayer.ADAPTER
    elif error.code in {LLMErrorCode.RATE_LIMIT, LLMErrorCode.HTTP_STATUS}:
        layer = RootCauseLayer.PROVIDER
    return ProviderDiagnosticResult(provider=response.provider, model=response.model, credential_status=credential_status, connectivity_status=ConnectivityStatus.NOT_CONFIGURED if error.code is LLMErrorCode.NOT_CONFIGURED else ConnectivityStatus.FAILURE, http_status=error.http_status, error_category=error.code, root_cause_layer=layer, retryable=error.retryable, latency_ms=response.duration_ms, message_sanitized=error.message)

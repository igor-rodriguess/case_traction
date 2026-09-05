"""Contratos estritos, portáveis e livres de credenciais para inferência LLM."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
ProviderName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class LLMContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LLMMessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class StructuredOutputMode(str, Enum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    TEXT = "text"


class LLMMessage(LLMContract):
    role: LLMMessageRole
    content: str = Field(min_length=1, max_length=30_000)


class LLMGenerationParameters(LLMContract):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)


class LLMRequest(LLMContract):
    """Pedido de inferência; não transporta SDK, credencial ou infraestrutura."""

    request_id: Identifier
    agent_role: Identifier
    messages: tuple[LLMMessage, ...] = Field(min_length=1)
    prompt_version: Identifier
    generation: LLMGenerationParameters = Field(default_factory=LLMGenerationParameters)
    expected_schema: dict[str, JsonValue]
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.JSON_SCHEMA
    max_output_tokens: int = Field(ge=1, le=32_768)
    timeout_seconds: float = Field(gt=0.0, le=300.0)
    contract_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")


class LLMUsage(LLMContract):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def total_matches_parts(self) -> "LLMUsage":
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens deve ser a soma de input_tokens e output_tokens.")
        return self


class LLMMetadata(LLMContract):
    prompt_version: Identifier
    finish_reason: str | None = Field(default=None, max_length=120)
    raw_response_id: Identifier | None = None
    attempt_count: int = Field(default=1, ge=1, le=3)


class LLMErrorCode(str, Enum):
    TIMEOUT = "timeout"
    PROVIDER_FAILURE = "provider_failure"
    INVALID_JSON = "invalid_json"
    INVALID_SCHEMA = "invalid_schema"
    UNSUPPORTED = "unsupported"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    HTTP_STATUS = "http_status"
    MODEL_NOT_FOUND = "model_not_found"
    REQUEST_SCHEMA_ERROR = "request_schema_error"
    RESPONSE_SCHEMA_ERROR = "response_schema_error"
    NETWORK_ERROR = "network_error"
    QUOTA_EXCEEDED = "quota_exceeded"


class LLMError(LLMContract):
    code: LLMErrorCode
    message: str = Field(min_length=1, max_length=500)
    retryable: bool
    http_status: int | None = Field(default=None, ge=100, le=599)


class LLMResponseStatus(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    PROVIDER_FAILURE = "provider_failure"
    INVALID_OUTPUT = "invalid_output"


class LLMResponse(LLMContract):
    """Resposta normalizada antes de qualquer decisão operacional."""

    request_id: Identifier
    response_id: Identifier | None = None
    provider: ProviderName
    model: ModelName
    status: LLMResponseStatus
    output: JsonValue | None = None
    usage: LLMUsage | None = None
    duration_ms: float = Field(ge=0.0)
    error: LLMError | None = None
    metadata: LLMMetadata
    contract_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")

    @model_validator(mode="after")
    def validate_status_shape(self) -> "LLMResponse":
        if self.status is LLMResponseStatus.SUCCESS:
            if self.error is not None or self.output is None:
                raise ValueError("Resposta success exige output e não aceita error.")
        elif self.error is None:
            raise ValueError("Resposta não bem-sucedida exige erro estruturado.")
        return self


class CredentialStatus(str, Enum):
    CONFIGURED = "configured"
    MISSING = "missing"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class ConnectivityStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NOT_CONFIGURED = "not_configured"


class RootCauseLayer(str, Enum):
    CONFIGURATION = "configuration"
    PROVIDER = "provider"
    ADAPTER = "adapter"
    NETWORK = "network"
    UNKNOWN = "unknown"


class ProviderDiagnosticResult(LLMContract):
    """Registro seguro de um smoke sem payload ou credencial."""

    provider: ProviderName
    model: ModelName
    credential_status: CredentialStatus
    connectivity_status: ConnectivityStatus
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_category: LLMErrorCode | None = None
    root_cause_layer: RootCauseLayer
    retryable: bool = False
    latency_ms: float = Field(ge=0.0)
    usage: LLMUsage | None = None
    message_sanitized: str = Field(min_length=1, max_length=500)

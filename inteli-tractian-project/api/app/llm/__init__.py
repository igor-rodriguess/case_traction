"""Contrato interno e provider fake para inferência LLM, sem SDK externo."""

from app.llm.contracts import (
    LLMError,
    LLMErrorCode,
    LLMGenerationParameters,
    LLMMessage,
    LLMMetadata,
    LLMRequest,
    LLMResponse,
    LLMResponseStatus,
    LLMUsage,
)
from app.llm.investigator import LLMInvestigatorBoundary, LLMOutputValidationError, parse_investigation_decision
from app.llm.provider import FakeLLMProvider, LLMProvider
from app.llm.real_providers import (
    CerebrasProvider, GeminiProvider, GroqProvider, ProviderCapabilities, ProviderConfig,
    ProviderName, RetryPolicy, create_provider, default_provider_configs,
)

__all__ = [
    "FakeLLMProvider", "LLMError", "LLMErrorCode", "LLMGenerationParameters", "LLMInvestigatorBoundary",
    "LLMMessage", "LLMMetadata", "LLMOutputValidationError", "LLMProvider", "LLMRequest", "LLMResponse",
    "LLMResponseStatus", "LLMUsage", "parse_investigation_decision",
    "CerebrasProvider", "GeminiProvider", "GroqProvider", "ProviderCapabilities", "ProviderConfig",
    "ProviderName", "RetryPolicy", "create_provider", "default_provider_configs",
]

"""Contrato interno e provider fake para inferência LLM, sem SDK externo."""

from app.llm.contracts import (
    CredentialStatus,
    ConnectivityStatus,
    LLMError,
    LLMErrorCode,
    LLMGenerationParameters,
    LLMMessage,
    LLMMetadata,
    LLMRequest,
    LLMResponse,
    LLMResponseStatus,
    LLMUsage,
    ProviderDiagnosticResult,
    RootCauseLayer,
    StructuredOutputMode,
)
from app.llm.investigator import (
    InvestigatorValidationCategory,
    InvestigatorRecoveryAction,
    InvestigatorValidationResult,
    InvestigatorValidationStage,
    LLMInvestigatorBoundary,
    LLMOutputValidationError,
    parse_investigation_decision,
    recovery_action,
    validate_investigation_decision,
)
from app.llm.provider import FakeLLMProvider, LLMProvider
from app.llm.real_providers import (
    CerebrasProvider, GeminiProvider, GroqProvider, ProviderCapabilities, ProviderConfig,
    ProviderName, RetryPolicy, create_provider, default_provider_configs, diagnostic_result,
)

__all__ = [
    "CredentialStatus", "ConnectivityStatus", "FakeLLMProvider", "LLMError", "LLMErrorCode", "LLMGenerationParameters", "LLMInvestigatorBoundary",
    "LLMMessage", "LLMMetadata", "LLMOutputValidationError", "LLMProvider", "LLMRequest", "LLMResponse",
    "LLMResponseStatus", "LLMUsage", "ProviderDiagnosticResult", "RootCauseLayer", "StructuredOutputMode", "parse_investigation_decision",
    "InvestigatorValidationCategory", "InvestigatorValidationResult", "InvestigatorValidationStage", "validate_investigation_decision",
    "InvestigatorRecoveryAction", "recovery_action",
    "CerebrasProvider", "GeminiProvider", "GroqProvider", "ProviderCapabilities", "ProviderConfig",
    "ProviderName", "RetryPolicy", "create_provider", "default_provider_configs", "diagnostic_result",
]

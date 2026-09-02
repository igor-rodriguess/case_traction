"""Fronteira de modelo do Understanding Agent.

Esta camada define **como** um modelo seria chamado, sem decidir **qual**
modelo. Nenhum modelo/base foi aprovado nos artefatos do projeto até a Etapa
04.7, portanto `resolve_structured_provider()` bloqueia deliberadamente em vez
de escolher um provedor disponível por conveniência.

Regra arquitetural: baseline prompt-only e um eventual modelo fine-tuned devem
partir da mesma família/base para que a comparação seja válida. Escolher um
provedor silenciosamente aqui invalidaria a comparação futura.

Nenhuma credencial é lida, embutida ou registrada por este módulo.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue


MODEL_SELECTION_STATUS = "BLOCKED_MODEL_SELECTION"

APPROVED_MODEL_BASE: str | None = None
"""Nenhuma base aprovada. Preencher somente por decisão humana registrada em
`datasets/approvals/`."""


class ModelCandidate(BaseModel):
    """Opção de modelo documentada para revisão humana, não uma escolha."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    family: str
    structured_output: str
    fine_tuning_path: str
    credential_env: str
    notes: str


MODEL_CANDIDATES: tuple[ModelCandidate, ...] = (
    ModelCandidate(
        provider="anthropic",
        family="claude",
        structured_output="tool-use / structured output nativo com JSON Schema",
        fine_tuning_path="indisponível para o aluno; comparação prompt-only vs SFT exigiria outro provedor",
        credential_env="ANTHROPIC_API_KEY",
        notes=(
            "Boa aderência a schema em prompt-only. Quebra o requisito de mesma "
            "família entre baseline e fine-tuned se o SFT ocorrer noutro provedor."
        ),
    ),
    ModelCandidate(
        provider="openai_compatible",
        family="gpt / endpoint compatível",
        structured_output="response_format json_schema (strict)",
        fine_tuning_path="SFT disponível na mesma família; preserva a comparação baseline vs fine-tuned",
        credential_env="OPENAI_API_KEY",
        notes=(
            "É a única família citada no material do curso: o alvo `agent-env` do "
            "Makefile prevê OPENAI_API_KEY/BASE_URL/MODEL em `agent/.env`. "
            "Citação não é aprovação."
        ),
    ),
    ModelCandidate(
        provider="local_open_weights",
        family="llama / qwen / mistral",
        structured_output="grammar/JSON-schema constrained decoding conforme runtime",
        fine_tuning_path="LoRA/SFT local sobre a mesma base; comparação mais controlada",
        credential_env="nenhuma",
        notes=(
            "Máximo controle experimental e custo zero de API, mas exige "
            "infraestrutura local e qualidade prompt-only tipicamente menor."
        ),
    ),
)


class ModelSelectionBlocked(RuntimeError):
    """Nenhum modelo/base foi aprovado para o piloto."""


class ModelInvocationError(RuntimeError):
    """O provedor falhou ao produzir uma resposta."""


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ModelResponse(BaseModel):
    """Resposta bruta do provedor, antes de qualquer validação de schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    content: JsonValue
    """Objeto JSON já desserializado quando o provedor suporta structured output;
    string quando o provedor devolve texto livre."""
    usage: TokenUsage = TokenUsage()
    provider_latency_ms: float | None = Field(default=None, ge=0)


@runtime_checkable
class StructuredModelProvider(Protocol):
    """Contrato mínimo exigido do provedor.

    O provider recebe um JSON Schema e devolve conteúdo. Ele nunca recebe o
    `TractianClient`, nunca recebe tools e nunca executa nada: o Understanding
    Agent é puramente interpretativo.
    """

    @property
    def model_id(self) -> str: ...

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, JsonValue],
    ) -> ModelResponse: ...


def resolve_structured_provider() -> StructuredModelProvider:
    """Falha de forma explícita enquanto não houver modelo aprovado.

    Não faz fallback, não lê variáveis de ambiente e não consome API externa.
    """

    if APPROVED_MODEL_BASE is None:
        raise ModelSelectionBlocked(
            "BLOCKED_MODEL_SELECTION: nenhum modelo/base foi aprovado para o "
            "baseline do Understanding Agent. Registre a decisão humana em "
            "datasets/approvals/ e defina APPROVED_MODEL_BASE antes de executar "
            "o runner. Opções documentadas em MODEL_CANDIDATES."
        )
    raise ModelSelectionBlocked(  # pragma: no cover - inalcançável na Etapa 05
        "APPROVED_MODEL_BASE definido, mas nenhum adaptador de provedor foi "
        "implementado para ele."
    )

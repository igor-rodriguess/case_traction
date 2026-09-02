"""Contrato tipado do Understanding Agent.

A fonte da verdade é `understanding_schema` em
`docs/architecture/04-6-synthetic-training-design.json`. Estes modelos são a
tradução Pydantic literal daquele JSON Schema Draft 2020-12: mesmos campos,
mesmos enums, mesmas obrigatoriedades e `additionalProperties: false`.

Divergência registrada em
`datasets/approvals/understanding-baseline-v1-decisions.json`: o campo
`confidence` é mantido por paridade com o contrato aprovado, por decisão humana
explícita de 2026-09-02.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0"


class UnderstandingModel(BaseModel):
    """Base estrita e imutável do contrato de Understanding.

    `extra="forbid"` rejeita campos inventados pelo modelo; `frozen=True` impede
    que uma camada posterior corrija silenciosamente uma interpretação.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# Entrada
# --------------------------------------------------------------------------- #


class AvailableContext(UnderstandingModel):
    """Contexto injetado pelo runtime, nunca escolhido pelo modelo."""

    tenant_ref: str | None
    asset_refs: tuple[str, ...] = ()
    role: str | None
    permissions: tuple[str, ...] = ()


class UnderstandingInput(UnderstandingModel):
    """Solicitação do cliente mais o contexto que o sistema já conhece."""

    message: str = Field(min_length=1)
    available_context: AvailableContext


# --------------------------------------------------------------------------- #
# Saída
# --------------------------------------------------------------------------- #


class RequestClass(str, Enum):
    CONTEXTUALIZE = "contextualize"
    INVESTIGATE = "investigate"
    EXECUTE = "execute"
    MIXED = "mixed"
    UNCLEAR = "unclear"


class IntentKind(str, Enum):
    INFORMATIONAL = "informational"
    INVESTIGATIVE = "investigative"
    ACTION_REQUEST = "action_request"
    HANDOFF = "handoff"


class QuestionKind(str, Enum):
    FACT = "fact"
    DIAGNOSIS = "diagnosis"
    COMPARISON = "comparison"
    PROCEDURE = "procedure"
    ACTION = "action"
    CLARIFICATION = "clarification"


class Intent(UnderstandingModel):
    intent_id: str = Field(min_length=1)
    kind: IntentKind
    summary: str
    target_entities: tuple[str, ...] = ()
    requested_outcome: str


class Question(UnderstandingModel):
    question_id: str = Field(min_length=1)
    text: str
    kind: QuestionKind
    depends_on: tuple[str, ...] = ()


class Entities(UnderstandingModel):
    """Somente entidades explicitamente presentes na mensagem ou no contexto."""

    assets: tuple[str, ...] = ()
    analyses: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    technical_terms: tuple[str, ...] = ()
    temporal_references: tuple[str, ...] = ()


class MissingInformation(UnderstandingModel):
    field: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    blocking: bool
    suggested_question: str | None


class RequestedAction(UnderstandingModel):
    """Reconhecimento de um pedido de impacto — nunca sua execução."""

    capability: str = Field(min_length=1)
    explicitly_requested: bool
    evidence_required: bool


class Constraints(UnderstandingModel):
    tenant_scope_known: bool
    permissions_known: bool
    # `const: false` no schema aprovado. Literal[False] torna estruturalmente
    # impossível o agente declarar-se autorizado a executar ACTIONs.
    action_execution_allowed: Literal[False] = False


class UnderstandingOutput(UnderstandingModel):
    """Representação estruturada do problema. Não é diagnóstico nem resposta."""

    request_class: RequestClass
    intents: tuple[Intent, ...]
    questions: tuple[Question, ...]
    entities: Entities
    investigation_targets: tuple[str, ...]
    missing_information: tuple[MissingInformation, ...]
    requested_actions: tuple[RequestedAction, ...]
    constraints: Constraints
    confidence: float = Field(ge=0.0, le=1.0)


# Campos do contrato que nenhuma métrica determinística consegue avaliar.
NOT_AUTOMATICALLY_SCORED: tuple[str, ...] = (
    "intents[].intent_id",
    "intents[].summary",
    "intents[].requested_outcome",
    "questions[].question_id",
    "questions[].text",
    "missing_information[].suggested_question",
)

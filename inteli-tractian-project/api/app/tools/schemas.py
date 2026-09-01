"""Schemas públicos e estritos da Tool Layer.

Identidade, headers, credenciais e controles de runtime não pertencem a estes
modelos: o ``RequestContext`` já está vinculado ao ``TractianClient``.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SearchQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Justification = Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=2000)]


class ToolInput(BaseModel):
    """Base que recusa campos não declarados na fronteira do futuro LLM."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class AnalysisStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    PENDING = "pending"
    INCONCLUSIVE = "inconclusive"


class KnowledgeType(str, Enum):
    PROCEDURE = "procedure"
    GLOSSARY = "glossary"
    GUIDANCE = "guidance"


class AssetCriticality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AssetIdInput(ToolInput):
    asset_id: Identifier = Field(description="Identificador do ativo investigado.")


class AssetPointInput(AssetIdInput):
    point_id: Identifier | None = Field(
        default=None,
        description="Ponto de medição específico; omita para usar o ponto padrão do ativo.",
    )


class ListAssetAnalysesInput(AssetIdInput):
    status: AnalysisStatus | None = Field(
        default=None,
        description="Filtra análises pelo estado conhecido; omita para listar todos os estados.",
    )


class AnalysisIdInput(ToolInput):
    analysis_id: Identifier = Field(description="Identificador da análise.")


class ModelIdInput(ToolInput):
    model_id: Identifier = Field(description="Identificador do modelo industrial.")


class KnowledgeSearchInput(ToolInput):
    query: SearchQuery = Field(description="Termos objetivos para buscar conhecimento industrial.")
    knowledge_type: KnowledgeType | None = Field(
        default=None,
        description="Tipo de documento; omita para pesquisar todos os tipos.",
    )


class KnowledgeDocumentInput(ToolInput):
    doc_id: Identifier = Field(description="Identificador de um documento conhecido.")


class AssetConfigChanges(ToolInput):
    criticality: AssetCriticality = Field(description="Nova criticidade operacional do ativo.")


class AssetConfigUpdateInput(AssetIdInput):
    changes: AssetConfigChanges
    justification: Justification = Field(description="Motivo auditável para solicitar a alteração.")


class AnalysisActionInput(AnalysisIdInput):
    justification: Justification = Field(description="Motivo auditável para solicitar a ação.")
    params: dict[str, JsonValue] | None = Field(
        default=None,
        description="Parâmetros JSON opcionais aceitos pelo contrato aberto da operação.",
    )


class ModelRetrainingInput(ModelIdInput):
    justification: Justification = Field(description="Motivo auditável para solicitar retreinamento.")
    params: dict[str, JsonValue] | None = Field(
        default=None,
        description="Parâmetros JSON opcionais aceitos pelo contrato aberto da operação.",
    )


class CaseEscalationInput(ToolInput):
    case_id: Identifier = Field(description="Identificador do caso a ser encaminhado.")
    justification: Justification = Field(description="Motivo auditável para solicitar o handoff humano.")
    params: dict[str, JsonValue] | None = Field(
        default=None,
        description="Contexto JSON opcional aceito pelo contrato aberto da operação.",
    )

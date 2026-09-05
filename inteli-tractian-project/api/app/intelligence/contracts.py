"""Contratos canônicos de Planner, contexto do Investigator e Reporter."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator, model_validator

from app.agents.understanding.schemas import UnderstandingOutput
from app.tools import get_investigator_tools


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
_READ_NAMES = frozenset(tool.name for tool in get_investigator_tools())


class IntelligenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityReference(IntelligenceModel):
    name: Identifier

    @field_validator("name")
    @classmethod
    def read_only(cls, value: str) -> str:
        if value not in _READ_NAMES:
            raise ValueError("Capability deve ser uma READ tool autorizada ao Investigator.")
        return value


class PlannerInput(IntelligenceModel):
    understanding: UnderstandingOutput
    permitted_context: dict[str, JsonValue] = Field(default_factory=dict)
    available_capabilities: tuple[CapabilityReference, ...] = Field(min_length=1)
    max_investigation_steps: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)


class PlanDependency(IntelligenceModel):
    objective_id: Identifier
    depends_on_objective_id: Identifier


class PlannerOutput(IntelligenceModel):
    plan_id: Identifier
    objectives: tuple[Text, ...] = Field(min_length=1)
    investigation_questions: tuple[Text, ...] = Field(min_length=1)
    suggested_capabilities: tuple[CapabilityReference, ...] = Field(min_length=1)
    dependencies: tuple[PlanDependency, ...] = ()
    missing_information: tuple[Text, ...] = ()
    stopping_conditions: tuple[Text, ...] = Field(min_length=1)
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)


class EvidenceSummary(IntelligenceModel):
    evidence_ids: tuple[Identifier, ...] = ()
    statuses: tuple[Identifier, ...] = ()
    relevant_results: tuple[dict[str, JsonValue], ...] = ()


class TraceSummary(IntelligenceModel):
    trace_id: Identifier
    tool_call_count: int = Field(ge=0)
    last_tool_name: Identifier | None = None
    last_call_id: Identifier | None = None


class CapabilityContract(IntelligenceModel):
    """Argumentos que a tool realmente aceita, copiados do seu próprio schema.

    Sem isto o Investigator recebe apenas o nome da capability e precisa supor os
    parâmetros — foi assim que `time_window`, `hours` e `window` apareceram na
    Etapa 09.5. Informar o contrato não amplia a superfície: continua sendo o
    mesmo schema que a Tool Layer valida.
    """

    name: Identifier
    accepted_arguments: tuple[Identifier, ...] = Field(min_length=1)
    required_arguments: tuple[Identifier, ...] = ()
    argument_schema: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def read_only(cls, value: str) -> str:
        if value not in _READ_NAMES:
            raise ValueError("Capability deve ser uma READ tool autorizada ao Investigator.")
        return value


class InvestigatorInput(IntelligenceModel):
    understanding: UnderstandingOutput
    plan: PlannerOutput
    phase: Identifier
    evidence: EvidenceSummary
    trace: TraceSummary
    permitted_capabilities: tuple[CapabilityReference, ...] = Field(min_length=1)
    capability_contracts: tuple[CapabilityContract, ...] = ()
    temporal_guidance: str | None = Field(default=None, max_length=600)
    investigation_step_count: int = Field(ge=0)
    max_investigation_steps: int = Field(ge=1)
    tool_call_count: int = Field(ge=0)
    max_tool_calls: int = Field(ge=1)
    last_observation: dict[str, JsonValue] | None = None
    missing_information: tuple[Text, ...] = ()


class ClaimStatus(str, Enum):
    SUPPORTED = "supported"
    QUALIFIED = "qualified"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"


class Claim(IntelligenceModel):
    claim_id: Identifier
    statement: Text
    supporting_evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    contradictory_evidence_ids: tuple[Identifier, ...] = ()
    limitation: str | None = Field(default=None, max_length=1_000)
    status: ClaimStatus = ClaimStatus.SUPPORTED


class InvestigationConclusion(IntelligenceModel):
    conclusion_id: Identifier
    claims: tuple[Claim, ...] = Field(min_length=1)
    supporting_evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    contradictory_evidence_ids: tuple[Identifier, ...] = ()
    limitations: tuple[Text, ...] = ()
    unresolved_points: tuple[Text, ...] = ()
    reason_codes: tuple[Identifier, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def claims_are_accounted_for(self) -> "InvestigationConclusion":
        known = set(self.supporting_evidence_ids) | set(self.contradictory_evidence_ids)
        referenced = {item for claim in self.claims for item in (*claim.supporting_evidence_ids, *claim.contradictory_evidence_ids)}
        if not referenced <= known:
            raise ValueError("Claims devem referenciar evidências declaradas pela conclusão.")
        return self


class ReporterInput(IntelligenceModel):
    case_id: Identifier
    trace_id: Identifier
    understanding: UnderstandingOutput
    plan: PlannerOutput
    conclusion: InvestigationConclusion
    evidence: EvidenceSummary
    trace: TraceSummary


class ReporterOutput(IntelligenceModel):
    report_id: Identifier
    case_id: Identifier
    audience: str = Field(default="tractian_engineering_team", pattern="^tractian_engineering_team$")
    executive_summary: Text
    investigation_performed: tuple[Text, ...] = Field(min_length=1)
    findings: tuple[Text, ...] = Field(min_length=1)
    claims: tuple[Claim, ...] = Field(min_length=1)
    evidence_references: tuple[Identifier, ...] = Field(min_length=1)
    contradictions: tuple[Text, ...] = ()
    limitations: tuple[Text, ...] = ()
    missing_information: tuple[Text, ...] = ()
    suggested_engineer_next_steps: tuple[Text, ...] = ()
    escalation_reason: str | None = Field(default=None, max_length=1_000)
    trace_id: Identifier

    @model_validator(mode="after")
    def claims_reference_report_evidence(self) -> "ReporterOutput":
        evidence = set(self.evidence_references)
        if any(not set(claim.supporting_evidence_ids) <= evidence for claim in self.claims):
            raise ValueError("Claims do relatório devem referenciar evidence_references.")
        return self

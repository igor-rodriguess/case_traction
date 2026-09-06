"""Conclusão factual, lineage e validação do Reporter sem heurística de LLM."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.tractian_client import EvidenceStatus, OperationKind
from app.intelligence.contracts import Claim, ClaimStatus, InvestigationConclusion, ReporterInput, ReporterOutput
from app.investigation.state import InvestigationDecisionType, InvestigationState
from app.observability import TraceEventType


class GroundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimLineage(GroundingModel):
    claim_id: str
    evidence_id: str
    source_call_id: str
    trace_sequence: int = Field(ge=1)
    tool_name: str
    operation_kind: OperationKind
    source_path: str
    valid: bool


class ReporterValidationResult(GroundingModel):
    valid: bool
    schema_valid: bool = True
    fabricated_claims: int = 0
    """Claims com id ausente da conclusao: invencao de fato."""

    altered_claims: int = 0
    """Claims de id conhecido com texto reescrito: infidelidade, nao invencao."""

    claim_preservation_rate: float = Field(ge=0, le=1)
    evidence_reference_preservation_rate: float = Field(ge=0, le=1)
    unsupported_claim_rate: float = Field(ge=0, le=1)
    limitations_preserved: bool
    unresolved_points_preserved: bool
    target_valid: bool
    violations: tuple[str, ...] = ()


def build_grounded_conclusion(state: InvestigationState) -> InvestigationConclusion:
    """Materializa somente fatos de detalhes de análise citados por ANSWER aceito."""

    if state.decision is None or state.decision.type is not InvestigationDecisionType.ANSWER:
        raise ValueError("Grounded conclusion exige decisão ANSWER.")
    by_id = {record.evidence_id: record for record in state.evidence_ledger.records}
    claims: list[Claim] = []
    limitations: list[str] = []
    for evidence_id in state.decision.supporting_evidence_ids:
        record = by_id.get(evidence_id)
        if record is None:
            raise ValueError("ANSWER referencia evidência inexistente.")
        if record.evidence_status not in {EvidenceStatus.COMPLETE, EvidenceStatus.PARTIAL}:
            raise ValueError("Evidence status não sustenta conclusão factual.")
        data = record.data if isinstance(record.data, dict) else {}
        if record.client_operation == "get_analysis" and {"id", "asset_id", "type", "severity", "confidence", "status"} <= set(data):
            statement = (
                f"A análise {data['id']} do ativo {data['asset_id']} está com status {data['status']}, "
                f"tipo {data['type']}, severidade {data['severity']} e confiança {data['confidence']}."
            )
        elif record.client_operation == "get_asset" and {"id", "name", "machine_type", "criticality", "sensor_status"} <= set(data):
            statement = (
                f"O ativo {data['id']} é {data['name']}, do tipo {data['machine_type']}, "
                f"com criticidade {data['criticality']} e sensor {data['sensor_status']}."
            )
        else:
            continue
        raw_limitations = data.get("limitations")
        item_limitations = tuple(str(item) for item in raw_limitations) if isinstance(raw_limitations, list) else ()
        limitation = "; ".join(item_limitations) if item_limitations else None
        claims.append(Claim(claim_id=f"claim_{data['id']}", statement=statement, supporting_evidence_ids=(evidence_id,), limitation=limitation, status=ClaimStatus.QUALIFIED if limitation else ClaimStatus.SUPPORTED))
        limitations.extend(item_limitations)
    if not claims:
        raise ValueError("Nenhuma evidência citada possui fato de análise materializável.")
    supporting = tuple(dict.fromkeys(eid for claim in claims for eid in claim.supporting_evidence_ids))
    return InvestigationConclusion(
        conclusion_id=f"conclusion_{state.case_id}", claims=tuple(claims), supporting_evidence_ids=supporting,
        limitations=tuple(dict.fromkeys(limitations)), unresolved_points=(), reason_codes=("GROUNDED_READ_EVIDENCE",),
    )


def build_claim_lineage(state: InvestigationState, conclusion: InvestigationConclusion) -> tuple[ClaimLineage, ...]:
    evidence = {record.evidence_id: record for record in state.evidence_ledger.records}
    events = {(event.call_id, event.sequence): event for event in state.trace.events}
    lineage: list[ClaimLineage] = []
    for claim in conclusion.claims:
        for evidence_id in claim.supporting_evidence_ids:
            record = evidence[evidence_id]
            event = events.get((record.source_call_id, record.source_trace_sequence))
            valid = bool(event and event.event_type is TraceEventType.TOOL_COMPLETED and event.tool_name == record.tool_name and event.operation_kind is OperationKind.READ)
            lineage.append(ClaimLineage(claim_id=claim.claim_id, evidence_id=evidence_id, source_call_id=record.source_call_id, trace_sequence=record.source_trace_sequence, tool_name=record.tool_name, operation_kind=OperationKind.READ, source_path=record.path, valid=valid))
    return tuple(lineage)


def validate_reporter_output(value: ReporterInput, output: ReporterOutput) -> ReporterValidationResult:
    expected_claims = {claim.claim_id: claim for claim in value.conclusion.claims}
    actual_claims = {claim.claim_id: claim for claim in output.claims}
    preserved = sum(actual_claims.get(key) == claim for key, claim in expected_claims.items())
    # Uma claim cujo id nao existe na conclusao e fabricacao. Uma claim com id
    # conhecido mas texto alterado e outra coisa: o relatorio continua invalido,
    # porem chamar as duas de UNSUPPORTED_CLAIM sugere invencao de fato onde
    # houve apenas reescrita — foi o que aconteceu quando o provider devolveu o
    # mesmo enunciado sem acentos.
    fabricated = sum(1 for key in actual_claims if key not in expected_claims)
    altered = sum(
        1 for key, claim in actual_claims.items() if key in expected_claims and expected_claims[key] != claim
    )
    unsupported = fabricated + altered
    expected_evidence = set(value.conclusion.supporting_evidence_ids) | set(value.conclusion.contradictory_evidence_ids)
    preserved_evidence = len(expected_evidence & set(output.evidence_references))
    claim_rate = preserved / len(expected_claims) if expected_claims else 1.0
    unsupported_rate = unsupported / len(actual_claims) if actual_claims else 0.0
    evidence_rate = preserved_evidence / len(expected_evidence) if expected_evidence else 1.0
    limitations_ok = set(value.conclusion.limitations) <= set(output.limitations)
    unresolved_ok = set(value.conclusion.unresolved_points) <= set(output.missing_information)
    target_ok = output.audience == "tractian_engineering_team"
    violations: list[str] = []
    if claim_rate < 1: violations.append("CLAIM_NOT_PRESERVED")
    if fabricated: violations.append("UNSUPPORTED_CLAIM")
    if altered: violations.append("CLAIM_TEXT_ALTERED")
    if evidence_rate < 1: violations.append("EVIDENCE_REFERENCE_NOT_PRESERVED")
    if not limitations_ok: violations.append("LIMITATION_NOT_PRESERVED")
    if not unresolved_ok: violations.append("UNRESOLVED_POINT_NOT_PRESERVED")
    if not target_ok: violations.append("INVALID_TARGET")
    return ReporterValidationResult(valid=not violations, fabricated_claims=fabricated, altered_claims=altered,
        claim_preservation_rate=claim_rate, evidence_reference_preservation_rate=evidence_rate, unsupported_claim_rate=unsupported_rate, limitations_preserved=limitations_ok, unresolved_points_preserved=unresolved_ok, target_valid=target_ok, violations=tuple(violations))

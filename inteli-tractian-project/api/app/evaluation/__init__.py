"""Camada determinística de avaliação: validação de split, cobertura e métricas."""

from app.evaluation.coverage import (
    AssetProbe,
    CaseCoverage,
    CoverageAlignment,
    DataCoverageReport,
    DescriptorAlignment,
    audit_case,
    audit_coverage,
    probe_asset,
    temporal_filtering_supported,
)
from app.evaluation.gates import (
    ComponentDecision,
    GateResult,
    evaluate_gates,
    overall_status,
    training_decisions,
)
from app.evaluation.dataset_validation import (
    DatasetValidationReport,
    SampleValidation,
    runtime_payload,
    validate_split_file,
)
from app.evaluation.taxonomy import (
    DEFAULT_PRIMARY_LAYER,
    EvaluationError,
    EvaluationErrorCode,
    FailureCategory,
    PrimaryLayer,
    QualityVerdict,
    RunStatus,
    TerminalStatus,
    TrainingAssessment,
    VALID_TERMINAL_STATUSES,
)

__all__ = [
    "AssetProbe",
    "CaseCoverage",
    "ComponentDecision",
    "CoverageAlignment",
    "DEFAULT_PRIMARY_LAYER",
    "DataCoverageReport",
    "DatasetValidationReport",
    "DescriptorAlignment",
    "EvaluationError",
    "EvaluationErrorCode",
    "FailureCategory",
    "GateResult",
    "PrimaryLayer",
    "QualityVerdict",
    "RunStatus",
    "SampleValidation",
    "TerminalStatus",
    "TrainingAssessment",
    "VALID_TERMINAL_STATUSES",
    "audit_case",
    "audit_coverage",
    "evaluate_gates",
    "overall_status",
    "probe_asset",
    "runtime_payload",
    "temporal_filtering_supported",
    "training_decisions",
    "validate_split_file",
]

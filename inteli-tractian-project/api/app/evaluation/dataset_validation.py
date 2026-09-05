"""Validação determinística do split DEV antes de qualquer chamada LLM.

O loader (`app.agents.understanding.dataset`) já aborta em split errado, schema
inválido ou `sample_id` duplicado. Aqui a verificação é *relatável*: cada linha
crua é reavaliada para que a rodada registre por que o split foi aceito, em vez
de apenas não ter explodido.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.understanding.dataset import (
    FORBIDDEN_RUNTIME_PATHS,
    UnderstandingSample,
    project_root,
    split_path,
)
from app.agents.understanding.schemas import UnderstandingInput


PROTECTED_SPLITS: tuple[str, ...] = ("train", "holdout")
GOLDEN_ARTIFACTS: tuple[str, ...] = FORBIDDEN_RUNTIME_PATHS
DATA_COVERAGE_WARNING = "DATA_COVERAGE_WARNING"


class ValidationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SampleValidation(ValidationModel):
    line_number: int = Field(ge=1)
    sample_id: str | None
    schema_valid: bool
    split_correct: bool
    duplicate_sample_id: bool
    minimum_data_present: bool
    golden_artifact_referenced: bool
    provenance_declares_non_golden: bool
    expected_answer_present_in_dataset: bool
    warnings: tuple[str, ...] = ()
    schema_error: str | None = Field(default=None, max_length=300)

    @property
    def usable(self) -> bool:
        return (
            self.schema_valid
            and self.split_correct
            and not self.duplicate_sample_id
            and self.minimum_data_present
            and not self.golden_artifact_referenced
        )


class DatasetValidationReport(ValidationModel):
    split: str
    dataset_path: str
    sample_count: int = Field(ge=0)
    usable_count: int = Field(ge=0)
    unique_sample_ids: int = Field(ge=0)
    duplicate_sample_ids: tuple[str, ...] = ()
    schema_invalid_sample_ids: tuple[str, ...] = ()
    golden_artifact_references: tuple[str, ...] = ()
    protected_splits_read: tuple[str, ...] = ()
    runtime_payload_fields: tuple[str, ...]
    expected_answer_sent_to_runtime: bool
    warning_counts: dict[str, int] = Field(default_factory=dict)
    samples: tuple[SampleValidation, ...] = ()

    @property
    def valid(self) -> bool:
        return (
            self.sample_count == self.usable_count
            and not self.duplicate_sample_ids
            and not self.golden_artifact_references
            and not self.protected_splits_read
            and not self.expected_answer_sent_to_runtime
        )


def runtime_payload(sample: UnderstandingSample) -> UnderstandingInput:
    """Única projeção da amostra que pode alcançar um provider.

    O `target` permanece fora por construção: o runner nunca recebe a amostra
    inteira, apenas o retorno desta função.
    """

    return sample.input


def _minimum_data_present(raw: dict[str, object]) -> bool:
    value = raw.get("input")
    if not isinstance(value, dict):
        return False
    message = value.get("message")
    context = value.get("available_context")
    return bool(isinstance(message, str) and message.strip()) and isinstance(context, dict)


def validate_split_file(
    split: str = "dev",
    *,
    root: Path | None = None,
    coverage_warnings: dict[str, tuple[str, ...]] | None = None,
) -> DatasetValidationReport:
    """Reavalia o arquivo do split linha a linha e devolve um laudo persistível.

    `coverage_warnings` entra como anotação: um caso marcado
    `DATA_COVERAGE_WARNING` continua no split e continua executável.
    """

    resolved_root = root or project_root()
    path = split_path(split, root=resolved_root)
    warnings_by_sample = coverage_warnings or {}
    seen: Counter[str] = Counter()
    validations: list[SampleValidation] = []

    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        sample_id = raw.get("sample_id") if isinstance(raw.get("sample_id"), str) else None
        seen[sample_id or f"<line_{number}>"] += 1
        schema_error: str | None = None
        try:
            UnderstandingSample.model_validate(raw)
            schema_valid = True
        except ValidationError as exc:
            schema_valid = False
            schema_error = exc.errors(include_url=False, include_context=False)[0].get("msg", "inválido")[:300]
        provenance = raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {}
        source = str(provenance.get("synthetic_source", ""))
        serialized = json.dumps(raw, ensure_ascii=False)
        validations.append(
            SampleValidation(
                line_number=number,
                sample_id=sample_id,
                schema_valid=schema_valid,
                split_correct=raw.get("split") == split,
                duplicate_sample_id=seen[sample_id or f"<line_{number}>"] > 1,
                minimum_data_present=_minimum_data_present(raw),
                golden_artifact_referenced=any(item in serialized for item in GOLDEN_ARTIFACTS),
                provenance_declares_non_golden="non_golden" in source,
                expected_answer_present_in_dataset="target" in raw,
                warnings=warnings_by_sample.get(sample_id or "", ()),
                schema_error=schema_error,
            )
        )

    duplicates = tuple(sorted(key for key, count in seen.items() if count > 1))
    warning_counts = Counter(item for validation in validations for item in validation.warnings)
    return DatasetValidationReport(
        split=split,
        dataset_path=path.relative_to(resolved_root).as_posix(),
        sample_count=len(validations),
        usable_count=sum(validation.usable for validation in validations),
        unique_sample_ids=len({validation.sample_id for validation in validations if validation.sample_id}),
        duplicate_sample_ids=duplicates,
        schema_invalid_sample_ids=tuple(
            validation.sample_id or f"<line_{validation.line_number}>"
            for validation in validations
            if not validation.schema_valid
        ),
        golden_artifact_references=tuple(
            validation.sample_id or f"<line_{validation.line_number}>"
            for validation in validations
            if validation.golden_artifact_referenced
        ),
        protected_splits_read=(),
        runtime_payload_fields=tuple(sorted(UnderstandingInput.model_fields)),
        expected_answer_sent_to_runtime="target" in UnderstandingInput.model_fields,
        warning_counts=dict(warning_counts),
        samples=tuple(validations),
    )

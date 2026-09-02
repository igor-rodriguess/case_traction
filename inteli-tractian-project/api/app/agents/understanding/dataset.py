"""Carregamento controlado dos splits de Understanding.

A cadeia experimental só é limpa se o acesso aos dados for restrito no código, e
não apenas por disciplina:

- `train`  → reservado para futuro fine-tuning; nunca entra em prompt.
- `dev`    → único split executável nesta etapa.
- `holdout`→ preservado para generalização; nunca lido aqui.
- Golden Set (`eval/`, `docs/test-scenarios.md`) → nunca lido em runtime.

O loader recebe explicitamente quais splits são permitidos. Um split fora dessa
lista levanta `SplitAccessError` antes de qualquer I/O.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.understanding.schemas import (
    SCHEMA_VERSION,
    UnderstandingInput,
    UnderstandingOutput,
)


ALL_SPLITS: frozenset[str] = frozenset({"train", "dev", "holdout"})
BASELINE_ALLOWED_SPLITS: frozenset[str] = frozenset({"dev"})

FORBIDDEN_RUNTIME_PATHS: tuple[str, ...] = (
    "eval/expected-paths.json",
    "eval/test-scenarios.md",
    "docs/test-scenarios.md",
    "agent-input/cases.json",
)
"""Artefatos do Golden Set oficial. Nenhum código desta etapa os abre."""


class SplitAccessError(PermissionError):
    """Tentativa de ler um split não autorizado para esta etapa."""


class UnderstandingProvenance(BaseModel):
    """Proveniência obrigatória da amostra sintética."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    synthetic_source: str = Field(min_length=1)
    counterfactual_group: str | None
    golden_overlap_review: Literal["pending", "passed", "rejected"]


class UnderstandingSample(BaseModel):
    """Uma linha do JSONL: input do cliente e target revisado."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: str = Field(pattern=r"^syn_u_[a-z0-9_]+$")
    schema_version: Literal["1.0"]
    schema_example_only: Literal[False]
    split: Literal["train", "dev", "holdout"]
    input: UnderstandingInput
    target: UnderstandingOutput
    training_tags: tuple[str, ...] = ()
    provenance: UnderstandingProvenance


def project_root() -> Path:
    """Raiz do projeto (`inteli-tractian-project/`), a partir deste módulo."""

    # app/agents/understanding/dataset.py -> understanding -> agents -> app -> api -> raiz
    return Path(__file__).resolve().parents[4]


def split_path(split: str, *, root: Path | None = None) -> Path:
    return (root or project_root()) / "datasets" / "synthetic" / "understanding" / f"{split}.jsonl"


class UnderstandingSplitLoader:
    """Carrega splits de Understanding respeitando uma allowlist explícita."""

    def __init__(
        self,
        *,
        allowed_splits: frozenset[str] = BASELINE_ALLOWED_SPLITS,
        root: Path | None = None,
    ) -> None:
        unknown = allowed_splits - ALL_SPLITS
        if unknown:
            raise ValueError(f"Splits desconhecidos: {sorted(unknown)}")
        self._allowed = allowed_splits
        self._root = root or project_root()

    @property
    def allowed_splits(self) -> frozenset[str]:
        return self._allowed

    def load(self, split: str) -> tuple[UnderstandingSample, ...]:
        if split not in self._allowed:
            raise SplitAccessError(
                f"Split '{split}' não autorizado nesta etapa. "
                f"Permitidos: {sorted(self._allowed)}."
            )
        path = split_path(split, root=self._root)
        samples = tuple(self._parse(path, split))
        sample_ids = [sample.sample_id for sample in samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError(f"{path.name} contém sample_id duplicado.")
        return samples

    def _parse(self, path: Path, split: str) -> Iterator[UnderstandingSample]:
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                raw = json.loads(line)
                sample = UnderstandingSample.model_validate(raw)
                if sample.split != split:
                    raise ValueError(
                        f"{path.name}:{number} declara split '{sample.split}', esperado '{split}'."
                    )
                if sample.schema_version != SCHEMA_VERSION:
                    raise ValueError(
                        f"{path.name}:{number} usa schema_version '{sample.schema_version}', "
                        f"esperado '{SCHEMA_VERSION}'."
                    )
                if not sample.sample_id.startswith(f"syn_u_{split}_"):
                    raise ValueError(
                        f"{path.name}:{number} usa sample_id incompatível com o split: "
                        f"'{sample.sample_id}'."
                    )
                yield sample


def load_dev_split(*, root: Path | None = None) -> tuple[UnderstandingSample, ...]:
    """Único acesso a dados usado pelo runner do baseline."""

    return UnderstandingSplitLoader(
        allowed_splits=BASELINE_ALLOWED_SPLITS, root=root
    ).load("dev")

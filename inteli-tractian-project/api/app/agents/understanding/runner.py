"""Runner do baseline prompt-only sobre o split DEV aprovado.

Carrega exclusivamente `datasets/synthetic/understanding/dev.jsonl`. Train,
holdout e Golden Set não são abertos por nenhum caminho deste módulo — a
restrição é imposta pela allowlist de `UnderstandingSplitLoader`.

Artefatos produzidos em `experiments/understanding/baseline-v1/`:

- `predictions.jsonl`   — uma linha por amostra, com prediction e comparação;
- `metrics.json`        — métricas determinísticas agregadas;
- `run-manifest.json`   — modelo, prompt, split, contagens, uso e status;
- `errors.jsonl`        — amostras sem output válido, preservadas;
- `showcase.json`       — seleção representativa para revisão humana.

Nenhum arquivo de dataset é escrito ou sobrescrito.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agents.understanding.agent import UnderstandingAgent, UnderstandingInvocation
from app.agents.understanding.dataset import (
    BASELINE_ALLOWED_SPLITS,
    FORBIDDEN_RUNTIME_PATHS,
    UnderstandingSample,
    UnderstandingSplitLoader,
    project_root,
)
from app.agents.understanding.metrics import UnderstandingEvaluator
from app.agents.understanding.observability import (
    AgentInvocationLog,
    AgentInvocationStatus,
)
from app.agents.understanding.prompts import PROMPT_VERSION
from app.agents.understanding.provider import StructuredModelProvider

BASELINE_ID = "understanding-baseline-v1"
DEFAULT_SPLIT = "dev"
FORBIDDEN_OUTPUT_DIRECTORIES: tuple[str, ...] = ("datasets", "eval", "agent-input")


class UnsafeOutputPathError(ValueError):
    """O runner tentou escrever em uma área de dados ou avaliação protegida."""


def default_output_dir(root: Path | None = None) -> Path:
    return (root or project_root()) / "experiments" / "understanding" / "baseline-v1"


def validate_output_dir(output_dir: Path, *, root: Path | None = None) -> Path:
    """Recusa destinos dentro de datasets, Golden Set ou inputs oficiais."""

    resolved = output_dir.resolve()
    resolved_root = (root or project_root()).resolve()
    for directory in FORBIDDEN_OUTPUT_DIRECTORIES:
        protected = (resolved_root / directory).resolve()
        if resolved == protected or protected in resolved.parents:
            raise UnsafeOutputPathError(
                f"Diretório de saída protegido: '{output_dir}'. Use experiments/ ou um "
                "diretório temporário fora de datasets/, eval/ e agent-input/."
            )
    return resolved


@dataclass(frozen=True)
class SampleResult:
    sample: UnderstandingSample
    invocation: UnderstandingInvocation
    field_comparison: dict[str, object] | None

    @property
    def schema_valid(self) -> bool:
        return self.invocation.schema_valid

    def as_prediction_row(self) -> dict[str, object]:
        record = self.invocation.record
        return {
            "sample_id": self.sample.sample_id,
            "split": self.sample.split,
            "training_tags": list(self.sample.training_tags),
            "input": self.sample.input.model_dump(mode="json"),
            "expected": self.sample.target.model_dump(mode="json"),
            "prediction": (
                self.invocation.output.model_dump(mode="json") if self.invocation.output else None
            ),
            "field_comparison": self.field_comparison,
            "schema_valid": self.schema_valid,
            "status": record.status.value,
            "latency_ms": record.duration_ms,
            "token_usage": record.usage.model_dump(mode="json"),
            "errors": (
                [] if record.failure is None else [record.failure.model_dump(mode="json")]
            ),
            "trace": {
                "trace_id": record.trace_id,
                "invocation_id": record.invocation_id,
                "component": record.component.value,
                "model_id": record.model_id,
                "prompt_version": record.prompt_version,
                "started_at": record.started_at.isoformat(),
                "completed_at": record.completed_at.isoformat(),
            },
        }


@dataclass(frozen=True)
class BaselineRun:
    results: tuple[SampleResult, ...]
    metrics: dict[str, object]
    manifest: dict[str, object]
    invocation_log: AgentInvocationLog


def run_baseline(
    provider: StructuredModelProvider,
    *,
    split: str = DEFAULT_SPLIT,
    root: Path | None = None,
    trace_id: str | None = None,
    limit: int | None = None,
) -> BaselineRun:
    """Executa o baseline sobre o split permitido e agrega as métricas."""

    if limit is not None and limit <= 0:
        raise ValueError("limit deve ser maior que zero.")

    loader = UnderstandingSplitLoader(allowed_splits=BASELINE_ALLOWED_SPLITS, root=root)
    samples = loader.load(split)
    if limit is not None:
        samples = samples[:limit]

    resolved_trace_id = trace_id or f"{BASELINE_ID}:{split}"
    agent = UnderstandingAgent(provider, trace_id=resolved_trace_id)
    log = AgentInvocationLog(resolved_trace_id)
    evaluator = UnderstandingEvaluator()

    results: list[SampleResult] = []
    started = datetime.now(timezone.utc)
    for sample in samples:
        invocation = agent.understand_request(sample.input)
        recorded = log.append(invocation.record)
        invocation = invocation.model_copy(update={"record": recorded})
        if invocation.output is None:
            evaluator.observe_failure(
                provider_error=invocation.record.status is AgentInvocationStatus.PROVIDER_ERROR
            )
            comparison = None
        else:
            comparison = evaluator.observe(
                request=sample.input,
                expected=sample.target,
                predicted=invocation.output,
            )
        results.append(SampleResult(sample, invocation, comparison))
    finished = datetime.now(timezone.utc)

    metrics = evaluator.as_dict()
    manifest = _build_manifest(
        provider=provider,
        split=split,
        results=results,
        metrics=metrics,
        started=started,
        finished=finished,
        loader=loader,
    )
    return BaselineRun(tuple(results), metrics, manifest, log)


def _build_manifest(
    *,
    provider: StructuredModelProvider,
    split: str,
    results: Sequence[SampleResult],
    metrics: dict[str, object],
    started: datetime,
    finished: datetime,
    loader: UnderstandingSplitLoader,
) -> dict[str, object]:
    latencies = sorted(result.invocation.record.duration_ms for result in results)
    usages = [result.invocation.record.usage for result in results]

    def _sum(attribute: str) -> int | None:
        values = [getattr(usage, attribute) for usage in usages]
        known = [value for value in values if value is not None]
        return sum(known) if known else None

    return {
        "baseline_id": BASELINE_ID,
        "status": "COMPLETED",
        "prompt_version": PROMPT_VERSION,
        "model_id": getattr(provider, "model_id", "unknown"),
        "provider_class": type(provider).__name__,
        "split": split,
        "allowed_splits": sorted(loader.allowed_splits),
        "splits_not_loaded": ["train", "holdout"],
        "golden_set_paths_not_loaded": list(FORBIDDEN_RUNTIME_PATHS),
        "few_shot_examples_in_prompt": 0,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "wall_clock_seconds": round((finished - started).total_seconds(), 3),
        "executions": len(results),
        "schema_valid": sum(1 for result in results if result.schema_valid),
        "schema_valid_rate": metrics.get("schema_valid_rate"),
        "latency_ms": {
            "min": latencies[0] if latencies else None,
            "median": latencies[len(latencies) // 2] if latencies else None,
            "max": latencies[-1] if latencies else None,
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
        },
        "token_usage_total": {
            "input_tokens": _sum("input_tokens"),
            "output_tokens": _sum("output_tokens"),
            "total_tokens": _sum("total_tokens"),
        },
        "estimated_cost_usd": None,
        "cost_note": "Não calculado: o provedor não fornece dados objetivos de preço.",
    }


# --------------------------------------------------------------------------- #
# Showcase
# --------------------------------------------------------------------------- #

SHOWCASE_CATEGORIES: tuple[str, ...] = (
    "simple_case",
    "multi_question_case",
    "ambiguous_or_missing_information_case",
    "explicit_entity_case",
    "action_request_case",
    "incorrect_or_partially_incorrect_case",
    "invalid_output_case",
)


def select_showcase(results: Sequence[SampleResult]) -> dict[str, object]:
    """Escolhe uma amostra representativa por categoria, sem esconder erros."""

    selected: dict[str, SampleResult] = {}

    def take(category: str, candidates: Sequence[SampleResult]) -> None:
        for candidate in candidates:
            if candidate.sample.sample_id not in {r.sample.sample_id for r in selected.values()}:
                selected[category] = candidate
                return
        if candidates:
            selected[category] = candidates[0]

    valid = [result for result in results if result.schema_valid]
    invalid = [result for result in results if not result.schema_valid]

    take(
        "simple_case",
        [
            result
            for result in valid
            if len(result.sample.target.questions) == 1
            and not result.sample.target.missing_information
            and not result.sample.target.requested_actions
        ],
    )
    take(
        "multi_question_case",
        [result for result in valid if len(result.sample.target.questions) > 1],
    )
    take(
        "ambiguous_or_missing_information_case",
        [result for result in valid if result.sample.target.missing_information],
    )
    take(
        "explicit_entity_case",
        [result for result in valid if result.sample.target.entities.assets],
    )
    take(
        "action_request_case",
        [result for result in valid if result.sample.target.requested_actions],
    )
    take("incorrect_or_partially_incorrect_case", [r for r in valid if _has_error(r)])
    take("invalid_output_case", invalid)

    return {
        "baseline_id": BASELINE_ID,
        "prompt_version": PROMPT_VERSION,
        "generated_from": "real baseline execution over the approved DEV split",
        "selection_note": (
            "Uma amostra por categoria. Casos incorretos são incluídos "
            "deliberadamente; nenhum caso ruim é omitido."
        ),
        "categories_absent_in_run": [
            category for category in SHOWCASE_CATEGORIES if category not in selected
        ],
        "cases": [
            {"showcase_category": category, **selected[category].as_prediction_row()}
            for category in SHOWCASE_CATEGORIES
            if category in selected
        ],
    }


def _has_error(result: SampleResult) -> bool:
    comparison = result.field_comparison
    if comparison is None:
        return True
    request_class = comparison.get("request_class", {})
    if isinstance(request_class, dict) and not request_class.get("match", True):
        return True
    ambiguity = comparison.get("ambiguity_detection", {})
    if isinstance(ambiguity, dict) and not ambiguity.get("match", True):
        return True
    targets = comparison.get("investigation_targets", {})
    if isinstance(targets, dict) and (targets.get("missing") or targets.get("spurious")):
        return True
    entities = comparison.get("entities", {})
    if isinstance(entities, dict):
        for report in entities.values():
            if isinstance(report, dict) and (report.get("missing") or report.get("spurious")):
                return True
    return bool(comparison.get("fabricated_identifiers"))


# --------------------------------------------------------------------------- #
# Persistência
# --------------------------------------------------------------------------- #


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[object]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_run(run: BaselineRun, output_dir: Path) -> dict[str, Path]:
    """Grava os artefatos do run. Não toca em nenhum arquivo de dataset."""

    validate_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [result.as_prediction_row() for result in run.results]
    paths = {
        "predictions": output_dir / "predictions.jsonl",
        "metrics": output_dir / "metrics.json",
        "manifest": output_dir / "run-manifest.json",
        "errors": output_dir / "errors.jsonl",
        "showcase": output_dir / "showcase.json",
        "invocations": output_dir / "agent-invocations.jsonl",
    }
    _write_jsonl(paths["predictions"], rows)
    _write_json(paths["metrics"], run.metrics)
    _write_json(paths["manifest"], run.manifest)
    _write_jsonl(paths["errors"], [row for row in rows if not row["schema_valid"]])
    _write_json(paths["showcase"], select_showcase(run.results))
    _write_jsonl(paths["invocations"], run.invocation_log.as_dicts())
    return paths

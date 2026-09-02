"""Testes do loader e do runner do baseline: fronteiras de split e artefatos.

Nenhum teste deste arquivo consome API externa. O "modelo" é um provider de
mentira que devolve o próprio target, opcionalmente perturbado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.understanding.dataset import (
    ALL_SPLITS,
    BASELINE_ALLOWED_SPLITS,
    FORBIDDEN_RUNTIME_PATHS,
    SplitAccessError,
    UnderstandingSplitLoader,
    load_dev_split,
    project_root,
    split_path,
)
from app.agents.understanding.prompts import PROMPT_VERSION
from app.agents.understanding.runner import (
    BASELINE_ID,
    UnsafeOutputPathError,
    default_output_dir,
    run_baseline,
    select_showcase,
    validate_output_dir,
    write_run,
)
from tests.understanding_fakes import EchoTargetProvider, FailingProvider

import run_understanding_baseline


DEV_SIZE = 60


# --------------------------------------------------------------------------- #
# Fronteiras de split
# --------------------------------------------------------------------------- #


def test_baseline_allows_only_dev() -> None:
    assert BASELINE_ALLOWED_SPLITS == frozenset({"dev"})
    assert ALL_SPLITS == frozenset({"train", "dev", "holdout"})


@pytest.mark.parametrize("split", ["train", "holdout"])
def test_loader_refuses_train_and_holdout(split: str) -> None:
    loader = UnderstandingSplitLoader(allowed_splits=BASELINE_ALLOWED_SPLITS)
    with pytest.raises(SplitAccessError) as error:
        loader.load(split)
    assert split in str(error.value)


def test_loader_refuses_before_touching_disk(tmp_path: Path) -> None:
    """A recusa acontece sem I/O: nem a existência do arquivo é consultada."""

    loader = UnderstandingSplitLoader(allowed_splits=BASELINE_ALLOWED_SPLITS, root=tmp_path)
    with pytest.raises(SplitAccessError):
        loader.load("holdout")


def test_loader_rejects_unknown_split_name() -> None:
    with pytest.raises(ValueError):
        UnderstandingSplitLoader(allowed_splits=frozenset({"golden"}))


def test_load_dev_split_returns_full_approved_dev() -> None:
    samples = load_dev_split()
    assert len(samples) == DEV_SIZE
    assert {sample.split for sample in samples} == {"dev"}
    assert all(sample.sample_id.startswith("syn_u_dev_") for sample in samples)
    assert len({sample.sample_id for sample in samples}) == DEV_SIZE


def test_dev_targets_satisfy_the_output_contract() -> None:
    for sample in load_dev_split():
        assert sample.target.constraints.action_execution_allowed is False
        assert sample.target.request_class.value in {
            "contextualize",
            "investigate",
            "execute",
            "mixed",
            "unclear",
        }


def _write_dev_rows(root: Path, rows: list[dict[str, object]]) -> None:
    path = split_path("dev", root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _first_dev_row() -> dict[str, object]:
    return json.loads(split_path("dev").read_text(encoding="utf-8").splitlines()[0])


def test_loader_rejects_unapproved_top_level_field(tmp_path: Path) -> None:
    row = _first_dev_row()
    row["unexpected"] = "must fail"
    _write_dev_rows(tmp_path, [row])
    with pytest.raises(ValueError):
        load_dev_split(root=tmp_path)


def test_loader_rejects_schema_examples(tmp_path: Path) -> None:
    row = _first_dev_row()
    row["schema_example_only"] = True
    _write_dev_rows(tmp_path, [row])
    with pytest.raises(ValueError):
        load_dev_split(root=tmp_path)


def test_loader_rejects_wrong_sample_prefix_and_duplicate_ids(tmp_path: Path) -> None:
    wrong_prefix = _first_dev_row()
    wrong_prefix["sample_id"] = "syn_u_train_9999"
    _write_dev_rows(tmp_path, [wrong_prefix])
    with pytest.raises(ValueError, match="incompatível"):
        load_dev_split(root=tmp_path)

    duplicate = _first_dev_row()
    _write_dev_rows(tmp_path, [duplicate, duplicate])
    with pytest.raises(ValueError, match="duplicado"):
        load_dev_split(root=tmp_path)


def test_golden_set_paths_are_never_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qualquer tentativa de abrir um artefato do Golden Set explode o teste."""

    root = project_root()
    forbidden = {(root / relative).resolve() for relative in FORBIDDEN_RUNTIME_PATHS}
    for split in ("train", "holdout"):
        forbidden.add(split_path(split).resolve())

    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if self.resolve() in forbidden:
            raise AssertionError(f"Arquivo proibido acessado: {self}")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    assert len(load_dev_split()) == DEV_SIZE


def test_forbidden_runtime_paths_cover_the_golden_set() -> None:
    assert "eval/expected-paths.json" in FORBIDDEN_RUNTIME_PATHS
    assert "eval/test-scenarios.md" in FORBIDDEN_RUNTIME_PATHS
    assert "docs/test-scenarios.md" in FORBIDDEN_RUNTIME_PATHS


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def _echo_provider(**kwargs: object) -> EchoTargetProvider:
    targets = {
        sample.input.message: sample.target.model_dump(mode="json")
        for sample in load_dev_split()
    }
    return EchoTargetProvider(targets, **kwargs)  # type: ignore[arg-type]


def test_runner_executes_dev_and_scores_a_perfect_model() -> None:
    run = run_baseline(_echo_provider(), limit=12)

    assert run.metrics["samples_total"] == 12
    assert run.metrics["schema_valid_rate"] == 1.0
    assert run.metrics["invalid_output_rate"] == 0.0
    assert run.metrics["intent_accuracy"]["request_class_accuracy"] == 1.0
    assert run.metrics["entity_extraction"]["overall"]["f1"] == 1.0
    assert run.metrics["investigation_targets"]["f1"] == 1.0
    assert run.metrics["fabrication"]["action_execution_allowed_violations"] == 0
    assert run.manifest["split"] == "dev"
    assert run.manifest["splits_not_loaded"] == ["train", "holdout"]
    assert run.manifest["few_shot_examples_in_prompt"] == 0
    assert run.manifest["prompt_version"] == PROMPT_VERSION
    assert run.manifest["executions"] == 12


def test_runner_refuses_a_non_dev_split() -> None:
    with pytest.raises(SplitAccessError):
        run_baseline(_echo_provider(), split="holdout")


def test_runner_records_every_invocation() -> None:
    run = run_baseline(_echo_provider(), limit=5, trace_id="trace-test")
    records = run.invocation_log.records
    assert len(records) == 5
    assert [record.sequence for record in records] == [1, 2, 3, 4, 5]
    assert all(record.component.value == "understanding_agent" for record in records)
    assert all(record.prompt_version == PROMPT_VERSION for record in records)
    assert all(record.model_id == "fake-echo-v0" for record in records)
    assert [result.invocation.record.sequence for result in run.results] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("limit", [0, -1])
def test_runner_rejects_non_positive_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="maior que zero"):
        run_baseline(_echo_provider(), limit=limit)


def test_runner_aggregates_token_usage_and_latency() -> None:
    run = run_baseline(_echo_provider(), limit=4)
    assert run.manifest["token_usage_total"] == {
        "input_tokens": 40,
        "output_tokens": 80,
        "total_tokens": 120,
    }
    assert run.manifest["latency_ms"]["max"] >= run.manifest["latency_ms"]["min"]
    assert run.manifest["estimated_cost_usd"] is None


def test_runner_preserves_errors_without_inventing_values() -> None:
    run = run_baseline(FailingProvider(), limit=3)
    assert run.metrics["provider_error_count"] == 3
    assert run.metrics["schema_valid_rate"] == 0.0
    assert run.metrics["scored_samples"] == 0
    for result in run.results:
        assert result.invocation.output is None
        assert result.field_comparison is None


def test_runner_records_invalid_output_samples() -> None:
    def drop_entities(_: str, content: object) -> object:
        payload = dict(content)  # type: ignore[arg-type]
        payload.pop("entities")
        return payload

    run = run_baseline(_echo_provider(perturb=drop_entities), limit=3)
    assert run.metrics["invalid_output_count"] == 3
    assert run.metrics["schema_valid_rate"] == 0.0


def test_runner_scores_a_degraded_model_below_perfect() -> None:
    def wrong_class(_: str, content: object) -> object:
        payload = dict(content)  # type: ignore[arg-type]
        payload["request_class"] = "unclear"
        return payload

    run = run_baseline(_echo_provider(perturb=wrong_class), limit=10)
    accuracy = run.metrics["intent_accuracy"]["request_class_accuracy"]
    assert 0.0 <= accuracy < 1.0


def test_metrics_flag_fabricated_identifiers() -> None:
    def invent_asset(_: str, content: object) -> object:
        payload = json.loads(json.dumps(content))
        payload["entities"]["assets"] = ["asset_INVENTADO_999"]
        return payload

    run = run_baseline(_echo_provider(perturb=invent_asset), limit=5)
    assert run.metrics["fabrication"]["fabricated_identifier_count"] == 5
    assert run.metrics["fabrication"]["samples_with_fabricated_identifier"]["hits"] == 5


def test_metrics_flag_tool_call_shaped_investigation_targets() -> None:
    def emit_tool_calls(_: str, content: object) -> object:
        payload = json.loads(json.dumps(content))
        payload["investigation_targets"] = ["get_asset_rms(asset_id)", "get_asset_baseline"]
        return payload

    run = run_baseline(_echo_provider(perturb=emit_tool_calls), limit=4)
    assert run.metrics["fabrication"]["samples_with_tool_call_shaped_target"]["hits"] == 4


# --------------------------------------------------------------------------- #
# Artefatos
# --------------------------------------------------------------------------- #


def test_write_run_serializes_all_artifacts(tmp_path: Path) -> None:
    run = run_baseline(_echo_provider(), limit=20)
    paths = write_run(run, tmp_path)

    rows = [
        json.loads(line)
        for line in paths["predictions"].read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 20
    first = rows[0]
    assert set(first) >= {
        "sample_id",
        "input",
        "expected",
        "prediction",
        "field_comparison",
        "schema_valid",
        "latency_ms",
        "token_usage",
        "errors",
    }
    assert json.loads(paths["metrics"].read_text(encoding="utf-8"))["samples_total"] == 20
    assert json.loads(paths["manifest"].read_text(encoding="utf-8"))["baseline_id"] == BASELINE_ID
    assert paths["errors"].read_text(encoding="utf-8") == ""

    showcase = json.loads(paths["showcase"].read_text(encoding="utf-8"))
    assert showcase["prompt_version"] == PROMPT_VERSION
    assert showcase["cases"]
    assert all("showcase_category" in case for case in showcase["cases"])


def test_write_run_does_not_touch_dataset_files(tmp_path: Path) -> None:
    dev = split_path("dev")
    before = dev.read_bytes()
    run = run_baseline(_echo_provider(), limit=3)
    write_run(run, tmp_path)
    assert dev.read_bytes() == before
    assert not any(tmp_path.glob("*.jsonl.bak"))


def test_default_output_dir_is_outside_datasets() -> None:
    output = default_output_dir()
    assert output.parts[-3:] == ("experiments", "understanding", "baseline-v1")
    assert "datasets" not in output.parts


@pytest.mark.parametrize("directory", ["datasets", "eval", "agent-input"])
def test_output_dir_rejects_protected_project_areas(directory: str) -> None:
    root = project_root()
    with pytest.raises(UnsafeOutputPathError):
        validate_output_dir(root / directory / "baseline-output")


def test_write_run_refuses_dataset_destination_before_io() -> None:
    run = run_baseline(_echo_provider(), limit=1)
    destination = project_root() / "datasets" / "forbidden-output"
    with pytest.raises(UnsafeOutputPathError):
        write_run(run, destination)
    assert not destination.exists()


def test_showcase_includes_bad_cases(tmp_path: Path) -> None:
    def break_ambiguity(_: str, content: object) -> object:
        payload = json.loads(json.dumps(content))
        payload["missing_information"] = []
        payload["request_class"] = "unclear"
        return payload

    run = run_baseline(_echo_provider(perturb=break_ambiguity), limit=30)
    showcase = select_showcase(run.results)
    categories = {case["showcase_category"] for case in showcase["cases"]}
    assert "incorrect_or_partially_incorrect_case" in categories
    bad = next(
        case
        for case in showcase["cases"]
        if case["showcase_category"] == "incorrect_or_partially_incorrect_case"
    )
    assert bad["field_comparison"] is not None


def test_showcase_reports_absent_categories() -> None:
    run = run_baseline(_echo_provider(), limit=60)
    showcase = select_showcase(run.results)
    # Sem erro e sem output inválido, as duas categorias negativas ficam ausentes
    # e isso é declarado, não escondido.
    assert set(showcase["categories_absent_in_run"]) == {
        "incorrect_or_partially_incorrect_case",
        "invalid_output_case",
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_blocks_on_model_selection(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = run_understanding_baseline.main(["--output-dir", str(tmp_path)])

    assert exit_code == 2
    assert "BLOCKED_MODEL_SELECTION" in capsys.readouterr().err

    manifest = json.loads((tmp_path / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "BLOCKED_MODEL_SELECTION"
    assert manifest["executions"] == 0
    assert manifest["external_api_calls"] == 0
    assert manifest["predictions_written"] is False
    assert manifest["showcase_written"] is False
    assert manifest["approved_model_base"] is None
    assert len(manifest["model_candidates"]) >= 2


def test_cli_writes_no_predictions_when_blocked(tmp_path: Path) -> None:
    run_understanding_baseline.main(["--output-dir", str(tmp_path)])
    assert not (tmp_path / "predictions.jsonl").exists()
    assert not (tmp_path / "showcase.json").exists()
    assert not (tmp_path / "metrics.json").exists()

"""Regressões do runner offline de Eval; nenhuma rede ou provider real."""

import json

import pytest

from app.eval import Criterion, Score, build_evaluation_input, load_barema
from scripts import run_eval


def _run(*, terminal: str = "SAFE_ESCALATION", evidence: list | None = None) -> dict:
    return {
        "run_id": "run_1",
        "sample_id": "sample_1",
        "terminal_status": terminal,
        "components": {},
        "state": {"trace_id": "trace_1", "request": {"message": "Investigue o ativo."}},
        "trace": [],
        "evidence_ledger": evidence or [],
    }


def test_deterministic_judge_accepts_safe_abstention_without_inventing_evidence() -> None:
    value = build_evaluation_input(_run(), evaluation_id="eval_1")

    result = run_eval.deterministic_judge(value, run_eval.JudgeRole.A, load_barema())
    grounding = next(item for item in result.criteria_scores if item.criterion is Criterion.EVIDENCE_GROUNDING)

    assert grounding.score is Score.ACCEPTABLE
    assert grounding.evidence_references == ()
    assert result.hard_failures == ()


def test_load_runs_reads_only_the_selected_experiment(tmp_path, monkeypatch) -> None:
    experiments = tmp_path / "experiments"
    for name, sample_id in (("cohort_a", "a"), ("cohort_b", "b")):
        folder = experiments / name
        folder.mkdir(parents=True)
        (folder / "runs.jsonl").write_text(
            json.dumps({**_run(), "sample_id": sample_id}) + "\n", encoding="utf-8"
        )
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)

    runs = run_eval.load_runs("cohort_b", limit=None, terminal=None)

    assert [item["sample_id"] for item in runs] == ["b"]


def test_load_runs_rejects_path_traversal(tmp_path, monkeypatch) -> None:
    (tmp_path / "experiments").mkdir()
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="inválido"):
        run_eval.load_runs("../outside", limit=None, terminal=None)


def test_load_runs_reports_malformed_json(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "experiments" / "broken"
    folder.mkdir(parents=True)
    (folder / "runs.jsonl").write_text("{not-json}\n", encoding="utf-8")
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="runs.jsonl:1"):
        run_eval.load_runs("broken", limit=None, terminal=None)


def test_main_exposes_evaluation_errors_in_status(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(run_eval, "OUTPUT_DIR", tmp_path / "eval-output")
    monkeypatch.setattr(run_eval, "load_local_env", lambda _path: None)
    monkeypatch.setattr(run_eval, "load_runs", lambda *_args: [_run()])
    monkeypatch.setattr(run_eval, "evaluate", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad run")))

    exit_code = run_eval.main(["--experiment", "cohort_a"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["status"] == "EVALUATED_WITH_ERRORS"
    assert output["input_runs"] == 1
    assert output["evaluations"] == 0
    assert output["evaluation_errors"] == 1

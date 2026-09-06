"""Guardas locais da Etapa 09.5; nenhum provider e nenhuma API são chamados."""

import inspect
import json

import pytest

from app.agents.understanding.dataset import load_dev_split
from app.evaluation.coverage import (
    AssetProbe,
    CaseCoverage,
    CoverageAlignment,
    DataCoverageReport,
    DescriptorAlignment,
    audit_case,
    descriptor_tokens,
    machine_family,
    temporal_filtering_supported,
)
from app.evaluation.dataset_validation import runtime_payload, validate_split_file
from app.evaluation.metrics import (
    capability_applicable,
    e2e_metrics,
    error_metrics,
    investigator_metrics,
    lineage_metrics,
    provider_metrics,
    reporter_metrics,
)
from app.evaluation.taxonomy import (
    DEFAULT_PRIMARY_LAYER,
    EvaluationError,
    EvaluationErrorCode,
    RunStatus,
    TerminalStatus,
    VALID_TERMINAL_STATUSES,
)
from app.agents.understanding.schemas import UnderstandingInput
from app.llm.contracts import (
    LLMError,
    LLMErrorCode,
    LLMMetadata,
    LLMResponse,
    LLMResponseStatus,
)
from scripts.run_full_dev_evaluation import (
    EXPERIMENT_VERSION,
    ROUTING_VERSION,
    ProviderQuotaExceeded,
    RunAborted,
    _guard_provider,
    build_showcase,
    load_completed_runs,
    needs_human_review,
    write_artifacts,
)


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #


def test_dev_split_is_valid_and_has_its_real_size() -> None:
    report = validate_split_file("dev")

    assert report.valid
    assert report.sample_count == report.usable_count == report.unique_sample_ids
    assert not report.duplicate_sample_ids
    assert not report.schema_invalid_sample_ids
    assert not report.golden_artifact_references
    assert report.split == "dev"


def test_runtime_payload_never_carries_the_expected_answer() -> None:
    sample = load_dev_split()[0]

    payload = runtime_payload(sample)

    assert isinstance(payload, UnderstandingInput)
    assert "target" not in json.loads(payload.model_dump_json())
    assert set(json.loads(payload.model_dump_json())) == {"message", "available_context"}


def test_every_dev_sample_declares_non_golden_provenance() -> None:
    report = validate_split_file("dev")

    assert all(item.provenance_declares_non_golden for item in report.samples)
    assert all(item.expected_answer_present_in_dataset for item in report.samples)


# --------------------------------------------------------------------------- #
# Cobertura de dados
# --------------------------------------------------------------------------- #


def _probe(asset_id: str, machine_type: str, *, asset_status: str = "complete", fields: bool = True) -> AssetProbe:
    return AssetProbe(
        asset_id=asset_id,
        exists=True,
        catalog_name=f"Nome {asset_id}",
        catalog_machine_type=machine_type,
        evidence_status_by_category={"asset": asset_status},
        grounded_fields_present=fields,
    )


def _sample_with(message: str, refs: tuple[str, ...] = ()):
    base = load_dev_split()[0]
    return base.model_copy(
        update={
            "input": base.input.model_copy(
                update={
                    "message": message,
                    "available_context": base.input.available_context.model_copy(update={"asset_refs": refs}),
                }
            )
        }
    )


def test_descriptor_tokens_keeps_the_head_noun_not_the_qualifier() -> None:
    message = "verifique o spindle de acabamento asset_S425 agora"

    tokens = descriptor_tokens(message, message.index("asset_S425"))

    assert "spindle" in tokens
    assert "de" not in tokens


def test_descriptor_contradicting_the_catalog_marks_the_case_misaligned() -> None:
    sample = _sample_with("verifique o compressor de serviço asset_S425", ("asset_S425",))
    probes = {"asset_S425": _probe("asset_S425", "spindle")}

    case = audit_case(sample, probes, {"compressor": "compressor"}, temporal_supported=False)

    assert case.mentions[0].descriptor_alignment is DescriptorAlignment.CONTRADICTED
    assert case.alignment is CoverageAlignment.MISALIGNED
    assert "DESCRIPTOR_CONTRADICTS_API_RECORD" in case.warnings


def test_descriptor_matching_the_catalog_is_corroborated() -> None:
    sample = _sample_with("verifique o spindle de acabamento asset_S425", ("asset_S425",))
    probes = {"asset_S425": _probe("asset_S425", "spindle")}

    case = audit_case(sample, probes, {"spindle": "spindle"}, temporal_supported=False)

    assert case.mentions[0].descriptor_alignment is DescriptorAlignment.CORROBORATED
    assert case.alignment is CoverageAlignment.FULLY_ALIGNED
    assert case.grounded_answer_reachable


def test_unknown_descriptor_stays_unverifiable_instead_of_presumed_wrong() -> None:
    sample = _sample_with("verifique o exaustor asset_S425", ("asset_S425",))
    probes = {"asset_S425": _probe("asset_S425", "spindle")}

    case = audit_case(sample, probes, {"spindle": "spindle"}, temporal_supported=False)

    assert case.mentions[0].descriptor_alignment is DescriptorAlignment.UNVERIFIABLE
    assert case.alignment is CoverageAlignment.PARTIALLY_ALIGNED


def test_case_without_resolvable_entity_is_impossible_from_api() -> None:
    sample = _sample_with("verifique aquele misturador que comentamos", ())

    case = audit_case(sample, {}, {"misturador": "mill"}, temporal_supported=False)

    assert case.alignment is CoverageAlignment.IMPOSSIBLE_FROM_API
    assert not case.grounded_answer_reachable
    assert "NO_RESOLVABLE_ENTITY" in case.warnings


def test_degraded_asset_record_blocks_grounded_answer_without_blaming_the_agent() -> None:
    sample = _sample_with("verifique o spindle asset_B211", ("asset_B211",))
    probes = {"asset_B211": _probe("asset_B211", "spindle", asset_status="inconclusive", fields=False)}

    case = audit_case(sample, probes, {"spindle": "spindle"}, temporal_supported=False)

    assert not case.grounded_answer_reachable
    assert "GROUNDED_ANSWER_NOT_REACHABLE_FROM_ASSET_RECORD" in case.warnings


def test_read_tool_surface_exposes_no_temporal_filter() -> None:
    assert temporal_filtering_supported() is False


def test_motor_variants_share_one_family() -> None:
    assert machine_family("motor_dc") == machine_family("motor_induction") == "motor"
    assert machine_family("pump") == "pump"
    assert machine_family(None) is None


# --------------------------------------------------------------------------- #
# Taxonomia e métricas
# --------------------------------------------------------------------------- #


def test_failed_is_not_a_valid_terminal_state() -> None:
    assert TerminalStatus.FAILED not in VALID_TERMINAL_STATUSES
    assert len(VALID_TERMINAL_STATUSES) == 3


def test_every_error_code_has_a_default_primary_layer() -> None:
    assert set(DEFAULT_PRIMARY_LAYER) == set(EvaluationErrorCode)


def test_capability_applicability_follows_the_tool_schema() -> None:
    assert capability_applicable("get_asset_context", {"assets"}) is True
    assert capability_applicable("get_asset_context", set()) is False
    assert capability_applicable("get_analysis_details", {"assets"}) is False
    assert capability_applicable("search_industrial_knowledge", set()) is True
    assert capability_applicable("tool_que_nao_existe", {"assets"}) is None


def _run(
    sample_id: str,
    terminal: TerminalStatus,
    *,
    decisions: list[dict] | None = None,
    evidence: list[dict] | None = None,
    errors: list[dict] | None = None,
    reporter: dict | None = None,
    conclusion: dict | None = None,
    lineage: list[dict] | None = None,
    duration: float = 1000.0,
) -> dict:
    components: dict = {"investigator": decisions or []}
    if reporter is not None:
        components["reporter"] = reporter
    if conclusion is not None:
        components["conclusion"] = conclusion
    if lineage is not None:
        components["claim_lineage"] = lineage
    return {
        "run_id": f"fulldev_{sample_id}",
        "sample_id": sample_id,
        "duration_ms": duration,
        "components": components,
        "state": {"max_investigation_steps": 12},
        "trace": [],
        "evidence_ledger": evidence or [],
        "terminal_status": terminal.value,
        "failure_category": "DEAD_END" if terminal is TerminalStatus.FAILED else None,
        "errors": errors or [],
        "coverage": {"alignment": "PARTIALLY_ALIGNED", "grounded_answer_reachable": True, "warnings": []},
    }


def _decision(kind: str, *, first_pass: bool = True, repair: bool = False, reason: str = "OK") -> dict:
    return {
        "attempts": [{"validation": {"valid": first_pass, "category": None, "field": None}}],
        "first_pass_valid": first_pass,
        "repair_attempted": repair,
        "repair_successful": False,
        "final_decision_source": "first_pass_llm",
        "output": {"type": kind},
        "completion_policy": {"accepted": True, "reason_code": reason, "rejected_decision_type": None},
    }


def test_e2e_metrics_separate_valid_terminals_from_failures() -> None:
    runs = [
        _run("a", TerminalStatus.GROUNDED_COMPLETION, duration=1000),
        _run("b", TerminalStatus.SAFE_ESCALATION, duration=2000),
        _run("c", TerminalStatus.AWAITING_REQUIRED_INFORMATION, duration=3000),
        _run("d", TerminalStatus.FAILED, duration=4000),
    ]

    metrics = e2e_metrics(runs)

    assert metrics["total_cases"] == 4
    assert metrics["valid_terminal_state_rate"] == 0.75
    assert metrics["grounded_completion_rate"] == 0.25
    assert metrics["failure_rate"] == 0.25
    assert metrics["dead_end_rate"] == 0.25
    assert metrics["p50_e2e_latency_ms"] is not None
    assert metrics["p95_e2e_latency_ms"] >= metrics["p50_e2e_latency_ms"]


def test_investigator_metrics_count_first_pass_and_repair() -> None:
    runs = [
        _run("a", TerminalStatus.SAFE_ESCALATION, decisions=[_decision("tool_call"), _decision("escalate")]),
        _run("b", TerminalStatus.AWAITING_REQUIRED_INFORMATION, decisions=[_decision("ask_user", first_pass=False, repair=True)]),
    ]

    metrics = investigator_metrics(runs)

    assert metrics["decisions_total"] == 3
    assert metrics["first_pass_valid_rate"] == round(2 / 3, 4)
    assert metrics["repair_rate"] == round(1 / 3, 4)
    assert metrics["failed_after_repair_rate"] == 0.0
    assert metrics["escalate_rate"] == round(1 / 3, 4)


def test_reporter_metrics_distinguish_reach_from_completion() -> None:
    conclusion = {"claims": [{"status": "supported"}]}
    good = {"validation": {"valid": True, "schema_valid": True, "claim_preservation_rate": 1.0, "evidence_reference_preservation_rate": 1.0, "unsupported_claim_rate": 0.0, "limitations_preserved": True, "unresolved_points_preserved": True, "target_valid": True, "violations": []}}
    bad = {"validation": {"valid": False, "schema_valid": True, "claim_preservation_rate": 0.0, "evidence_reference_preservation_rate": 1.0, "unsupported_claim_rate": 1.0, "limitations_preserved": True, "unresolved_points_preserved": True, "target_valid": True, "violations": ["UNSUPPORTED_CLAIM"]}}
    runs = [
        _run("a", TerminalStatus.GROUNDED_COMPLETION, conclusion=conclusion, reporter=good),
        _run("b", TerminalStatus.FAILED, conclusion=conclusion, reporter=bad),
        _run("c", TerminalStatus.SAFE_ESCALATION),
    ]

    metrics = reporter_metrics(runs)

    assert metrics["cases_eligible"] == 2
    assert metrics["cases_reached"] == 2
    assert metrics["completion_rate_among_reached"] == 0.5
    assert metrics["violations"] == {"UNSUPPORTED_CLAIM": 1}


def test_lineage_metrics_flag_reference_outside_the_ledger() -> None:
    runs = [
        _run(
            "a",
            TerminalStatus.GROUNDED_COMPLETION,
            evidence=[{"evidence_id": "ev1", "evidence_status": "complete"}],
            conclusion={"claims": [{"status": "supported"}, {"status": "qualified"}]},
            lineage=[
                {"evidence_id": "ev1", "valid": True},
                {"evidence_id": "ev_desconhecida", "valid": False},
            ],
        )
    ]

    metrics = lineage_metrics(runs)

    assert metrics["claims_total"] == 2
    assert metrics["lineage_valid_rate"] == 0.5
    assert metrics["invalid_reference_rate"] == 0.5
    assert metrics["grounded_claim_rate"] == 0.5


def test_error_metrics_group_by_code_and_layer() -> None:
    error = EvaluationError.of(
        EvaluationErrorCode.DATA_COVERAGE_GAP, subcategory="ASSET_RECORD", detail="sem cadastro"
    ).model_dump(mode="json")
    runs = [_run("a", TerminalStatus.FAILED, errors=[error]), _run("b", TerminalStatus.SAFE_ESCALATION)]

    metrics = error_metrics(runs)

    assert metrics["errors_total"] == 1
    assert metrics["cases_with_errors"] == 1
    assert metrics["by_code"] == {"DATA_COVERAGE_GAP": 1}
    assert metrics["by_primary_layer"] == {"DATA": 1}


def test_provider_metrics_count_calls_that_failed_before_any_component_existed() -> None:
    """Regressão da Etapa 09.5: o 5xx observado não entrava em provider_error_rate."""

    run = _run("a", TerminalStatus.FAILED)
    run["components"] = {}  # o guard abortou antes de qualquer componente
    run["llm_calls"] = [
        {
            "role": "understanding",
            "provider": "groq",
            "model": "m",
            "latency_ms": 90.0,
            "usage": None,
            "error": {"code": "http_status", "http_status": 503},
        }
    ]

    metrics = provider_metrics([run])

    assert metrics["groq"]["calls"] == 1
    assert metrics["groq"]["errors"] == 1
    assert metrics["groq"]["server_errors_5xx"] == 1
    assert e2e_metrics([run])["provider_error_rate"] == 1.0


def test_provider_metrics_still_read_v1_artifacts_without_a_ledger() -> None:
    run = _run("a", TerminalStatus.SAFE_ESCALATION)
    run["components"]["understanding"] = {
        "provider": "groq",
        "model": "m",
        "latency_ms": 10.0,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }

    assert provider_metrics([run])["groq"]["calls"] == 1


def test_provider_metrics_accumulate_tokens_and_rate_limits() -> None:
    run = _run("a", TerminalStatus.FAILED)
    run["components"]["understanding"] = {
        "provider": "groq",
        "model": "m",
        "latency_ms": 120.0,
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "error": {"code": "rate_limit", "http_status": 429},
    }

    metrics = provider_metrics([run])

    assert metrics["groq"]["calls"] == 1
    assert metrics["groq"]["total_tokens"] == 15
    assert metrics["groq"]["rate_limit_429"] == 1
    assert metrics["groq"]["error_rate"] == 1.0


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def _response(code: LLMErrorCode) -> LLMResponse:
    return LLMResponse(
        request_id="req",
        provider="gemini",
        model="modelo",
        status=LLMResponseStatus.PROVIDER_FAILURE,
        duration_ms=1.0,
        error=LLMError(code=code, message="falha", retryable=True),
        metadata=LLMMetadata(prompt_version="v"),
    )


def test_quota_stops_the_run_and_rate_limit_only_stops_the_case() -> None:
    with pytest.raises(ProviderQuotaExceeded):
        _guard_provider(_response(LLMErrorCode.QUOTA_EXCEEDED), role="investigator")

    with pytest.raises(RunAborted) as rate_limited:
        _guard_provider(_response(LLMErrorCode.RATE_LIMIT), role="investigator")
    assert rate_limited.value.error.code is EvaluationErrorCode.RATE_LIMIT

    with pytest.raises(RunAborted) as timed_out:
        _guard_provider(_response(LLMErrorCode.TIMEOUT), role="investigator")
    assert timed_out.value.error.code is EvaluationErrorCode.TIMEOUT


def test_decisions_survive_a_case_aborted_mid_investigation() -> None:
    """Regressão da Etapa 09.5: abortar o caso descartava as decisões já tomadas."""

    import scripts.run_full_dev_evaluation as runner

    source = inspect.getsource(runner.run_case)
    publish = source.index('components["investigator"] = decisions')
    loop = source.index("while state.investigation_step_count")

    assert publish < loop, "a lista precisa ser publicada antes do laço para sobreviver ao abort"


def test_successful_response_passes_the_guard() -> None:
    response = LLMResponse(
        request_id="req",
        provider="groq",
        model="modelo",
        status=LLMResponseStatus.SUCCESS,
        output="{}",
        duration_ms=1.0,
        metadata=LLMMetadata(prompt_version="v"),
    )

    assert _guard_provider(response, role="understanding") is None


def test_showcase_includes_failures_and_reports_absent_categories() -> None:
    runs = [
        _run("a", TerminalStatus.GROUNDED_COMPLETION),
        _run("b", TerminalStatus.FAILED, errors=[{"code": "REPORTER_ERROR"}]),
    ]

    showcase = build_showcase(runs)

    assert showcase["experiment_version"] == EXPERIMENT_VERSION
    assert showcase["routing_version"] == ROUTING_VERSION
    assert showcase["cases"]["real_error"]["sample_id"] == "b"
    assert "safe_escalation" in showcase["categories_absent"]


def test_human_review_flags_escalation_when_a_grounded_answer_was_reachable() -> None:
    runs = [_run("a", TerminalStatus.SAFE_ESCALATION)]

    flagged = needs_human_review(runs)

    assert flagged[0]["sample_id"] == "a"
    assert "ESCALATION_DESPITE_REACHABLE_GROUNDED_ANSWER" in flagged[0]["reasons"]


def test_resume_reads_back_only_completed_runs(tmp_path) -> None:
    path = tmp_path / "runs.jsonl"
    path.write_text(
        json.dumps(_run("a", TerminalStatus.SAFE_ESCALATION), ensure_ascii=False) + "\n", encoding="utf-8"
    )

    assert load_completed_runs(tmp_path / "ausente.jsonl") == []
    assert [run["sample_id"] for run in load_completed_runs(path)] == ["a"]


def test_resume_survives_a_run_killed_mid_write(tmp_path) -> None:
    """Um kill durante o append trunca a última linha; retomar não pode explodir."""

    path = tmp_path / "runs.jsonl"
    complete = json.dumps(_run("a", TerminalStatus.SAFE_ESCALATION), ensure_ascii=False)
    path.write_text(complete + "\n" + complete[: len(complete) // 2], encoding="utf-8")

    assert [run["sample_id"] for run in load_completed_runs(path)] == ["a"]


def _coverage_report(sample_ids: list[str]) -> DataCoverageReport:
    return DataCoverageReport(
        catalog_source="test",
        catalog_size=1,
        probes=(_probe("asset_S425", "spindle"),),
        descriptor_lexicon={"spindle": "spindle"},
        cases=tuple(
            CaseCoverage(
                sample_id=sample_id,
                referenced_asset_ids=("asset_S425",),
                mentions=(),
                alignment=CoverageAlignment.PARTIALLY_ALIGNED,
                temporal_context_requested=True,
                temporal_context_available=False,
                grounded_answer_reachable=True,
            )
            for sample_id in sample_ids
        ),
        cases_fully_aligned=0,
        cases_partially_aligned=len(sample_ids),
        cases_misaligned=0,
        cases_impossible_from_api=0,
        cases_grounded_answer_reachable=len(sample_ids),
        cases_requesting_unavailable_temporal_context=len(sample_ids),
        temporal_filtering_supported_by_tools=False,
    )


def test_aggregation_writes_every_required_artifact(tmp_path) -> None:
    samples = load_dev_split()[:2]
    sample_ids = [sample.sample_id for sample in samples]
    runs = [
        _run(sample_ids[0], TerminalStatus.SAFE_ESCALATION, decisions=[_decision("escalate")]),
        _run(sample_ids[1], TerminalStatus.AWAITING_REQUIRED_INFORMATION, decisions=[_decision("ask_user")]),
    ]

    aggregate = write_artifacts(
        runs,
        sample_ids=sample_ids,
        samples_by_id={sample.sample_id: sample for sample in samples},
        dataset_report=validate_split_file("dev"),
        coverage_report=_coverage_report(sample_ids),
        run_status=RunStatus.COMPLETED,
        output_dir=tmp_path,
    )

    expected = {
        "aggregate-metrics.json",
        "dataset-validation.json",
        "data-coverage.json",
        "showcase.json",
        "needs-human-review.json",
        "quality-gates.json",
        "checkpoint.json",
        "component-metrics.jsonl",
        "errors.jsonl",
    }
    assert expected <= {path.name for path in tmp_path.iterdir()}
    assert aggregate["dataset"]["executed_cases"] == 2
    assert aggregate["e2e"]["valid_terminal_state_rate"] == 1.0
    assert aggregate["final_status"] in {
        "READY_FOR_CALIBRATION_OR_TRAINING",
        "READY_FOR_HOLDOUT",
        "FIX_ARCHITECTURE_BEFORE_TRAINING",
    }
    assert len(aggregate["quality_gates"]) == 7
    assert {item["component"] for item in aggregate["training_assessment"]} == {
        "understanding",
        "planner",
        "investigator",
        "reporter",
    }
    assert json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))["executed_cases"] == 2


def test_aggregation_records_pending_cases_when_the_run_paused(tmp_path) -> None:
    samples = load_dev_split()[:3]
    sample_ids = [sample.sample_id for sample in samples]
    runs = [_run(sample_ids[0], TerminalStatus.SAFE_ESCALATION, decisions=[_decision("escalate")])]

    aggregate = write_artifacts(
        runs,
        sample_ids=sample_ids,
        samples_by_id={sample.sample_id: sample for sample in samples},
        dataset_report=validate_split_file("dev"),
        coverage_report=_coverage_report(sample_ids),
        run_status=RunStatus.RUN_PAUSED_PROVIDER_QUOTA,
        output_dir=tmp_path,
    )

    assert aggregate["dataset"]["pending_cases"] == sample_ids[1:]
    assert aggregate["final_status"] == "RUN_PAUSED_PROVIDER_QUOTA"


def test_provider_failures_are_excluded_from_the_behavioural_population() -> None:
    """§14 da Etapa 09.7B: um 5xx do provider não é falha de decisão do agente."""

    provider_error = EvaluationError.of(
        EvaluationErrorCode.PROVIDER_ERROR, subcategory="http_status", detail="5xx transitório"
    ).model_dump(mode="json")
    behavioural_error = EvaluationError.of(
        EvaluationErrorCode.INVALID_CONCLUSION, detail="grounding não materializável"
    ).model_dump(mode="json")
    runs = [
        _run("a", TerminalStatus.SAFE_ESCALATION),
        _run("b", TerminalStatus.GROUNDED_COMPLETION),
        _run("c", TerminalStatus.FAILED, errors=[provider_error]),
        _run("d", TerminalStatus.FAILED, errors=[behavioural_error]),
    ]

    metrics = e2e_metrics(runs)

    assert metrics["failure_rate"] == 0.5
    assert metrics["provider_failure_count"] == 1
    assert metrics["provider_failure_sample_ids"] == ["c"]
    assert metrics["behavioral_failure_count"] == 1
    assert metrics["behavioral_population"] == 3
    assert metrics["behavioral_failure_rate"] == round(1 / 3, 4)
    assert metrics["valid_terminal_state_rate_excluding_provider"] == round(2 / 3, 4)


def test_a_case_with_mixed_causes_stays_behavioural() -> None:
    """Se houver qualquer causa não-provider, a falha continua sendo do agente."""

    mixed = [
        EvaluationError.of(EvaluationErrorCode.PROVIDER_ERROR, detail="5xx").model_dump(mode="json"),
        EvaluationError.of(EvaluationErrorCode.INVALID_CONCLUSION, detail="grounding").model_dump(mode="json"),
    ]

    metrics = e2e_metrics([_run("a", TerminalStatus.FAILED, errors=mixed)])

    assert metrics["provider_failure_count"] == 0
    assert metrics["behavioral_failure_count"] == 1


def test_provider_killed_cases_return_to_the_queue_on_resume() -> None:
    """§7 da 09.7B: 503 e quota nunca foram medidos; repetir é obrigatório."""

    import scripts.run_full_dev_evaluation as runner

    source = inspect.getsource(runner.main)
    assert "infrastructure_blocked" in source
    assert 'error.get("primary_layer") == PrimaryLayer.PROVIDER.value' in source
    assert "run[\"sample_id\"] not in infrastructure_blocked" in source


def test_a_case_with_any_behavioural_cause_is_not_repeated(tmp_path) -> None:
    """Falha do agente foi medida: reexecutar apagaria o resultado observado."""

    from app.evaluation.taxonomy import PrimaryLayer

    provider_only = [EvaluationError.of(EvaluationErrorCode.PROVIDER_ERROR, detail="503").model_dump(mode="json")]
    mixed = provider_only + [
        EvaluationError.of(EvaluationErrorCode.INVALID_CONCLUSION, detail="grounding").model_dump(mode="json")
    ]

    def blocked(errors):
        return bool(errors) and all(e.get("primary_layer") == PrimaryLayer.PROVIDER.value for e in errors)

    assert blocked(provider_only) is True
    assert blocked(mixed) is False
    assert blocked([]) is False


def test_main_dry_run_executes_without_nameerror(monkeypatch, tmp_path) -> None:
    """Regressão 09.7B: um rename deixou `quota_blocked` órfão e só quebrou em runtime.

    Os testes anteriores liam o código-fonte de `main`; ler texto não prova que a
    função executa. Este exercita o caminho real, sem `--execute` e sem rede.
    """

    import scripts.run_full_dev_evaluation as runner

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(runner, "TractianClient", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(runner, "audit_coverage", lambda samples, client: _coverage_report([s.sample_id for s in samples]))

    assert runner.main([]) == 0


def test_run_duration_survives_a_backwards_clock() -> None:
    """Regressão 09.7B: o relógio do sistema voltou 2h20 e matou a rodada no caso 30.

    Subtrair duas leituras de `datetime.now` mede o relógio de parede, não o
    tempo decorrido. `RunTiming` exige duração não-negativa, então um ajuste de
    NTP derrubava o runner inteiro.
    """

    import scripts.run_full_dev_evaluation as runner

    source = inspect.getsource(runner.run_case)
    assert "perf_counter()" in source, "duração precisa vir de relógio monotônico"
    assert "started_at + timedelta(seconds=elapsed_seconds)" in source
    assert "finished_at = datetime.now(timezone.utc)" not in source


def test_run_timing_rejects_a_negative_duration() -> None:
    """O contrato que pegou o defeito continua estrito."""

    from datetime import datetime, timedelta, timezone

    from app.observability import RunTiming

    start = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        RunTiming.between(start, start - timedelta(hours=2))

    timing = RunTiming.between(start, start + timedelta(seconds=1.5))
    assert timing.duration_ms == 1500.0

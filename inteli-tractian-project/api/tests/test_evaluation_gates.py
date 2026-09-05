"""Os quality gates da Etapa 09.5 precisam reprovar; testá-los é testar o critério."""

from app.evaluation.gates import evaluate_gates, overall_status, training_decisions
from app.evaluation.taxonomy import QualityVerdict, TrainingAssessment


def _aggregate(**overrides):
    base = {
        "run_status": "COMPLETED",
        "e2e": {
            "total_cases": 60,
            "valid_terminal_state_rate": 1.0,
            "dead_end_rate": 0.0,
            "safe_escalation_rate": 0.4,
            "awaiting_information_rate": 0.2,
            "provider_error_rate": 0.0,
        },
        "investigator": {
            "first_pass_valid_rate": 1.0,
            "failed_after_repair_rate": 0.0,
            "invalid_tool_rate": 0.0,
            "invalid_argument_rate": 0.0,
            "forbidden_action_count": 0,
            "loop_rate": 0.0,
            "repeated_tool_rate": 0.0,
            "average_tools": 1.5,
        },
        "evidence_and_lineage": {
            "claims_total": 10,
            "lineage_valid_rate": 1.0,
            "unsupported_claim_rate": 0.0,
            "invalid_reference_rate": 0.0,
        },
        "reporter": {
            "cases_eligible": 10,
            "cases_reached": 10,
            "completion_rate_among_reached": 1.0,
            "claim_preservation_rate": 1.0,
            "unsupported_claim_rate": 0.0,
        },
        "errors": {"by_code": {}},
        "data_coverage_correlation": {
            "cases_grounded_answer_reachable": 37,
            "grounded_completion_rate_when_reachable": 0.7,
        },
        "providers": {"gemini": {"calls": 100, "errors": 0, "rate_limit_429": 0, "timeouts": 0}},
        "understanding": {
            "schema_valid_rate": 1.0,
            "intent_accuracy": {"request_class_accuracy": 0.95},
            "entity_extraction": {"overall": {"f1": 0.9}},
            "fabrication": {"fabricated_identifier_count": 0},
        },
        "planner": {
            "cases_reached": 60,
            "schema_valid_rate": 1.0,
            "relevant_capability_rate": 0.95,
            "unnecessary_capability_rate": 0.05,
            "plan_completion_rate": 0.5,
        },
        "security": {"action_decisions": 0, "action_tools_executed": 0},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def _coverage(**overrides):
    base = {
        "cases_fully_aligned": 55,
        "cases_partially_aligned": 5,
        "cases_misaligned": 0,
        "cases_impossible_from_api": 0,
        "cases_requesting_unavailable_temporal_context": 0,
    }
    base.update(overrides)
    return base


def _by_name(gates):
    return {gate.dimension: gate.verdict for gate in gates}


def test_healthy_run_passes_every_dimension_and_reaches_holdout() -> None:
    aggregate = _aggregate()
    gates = evaluate_gates(aggregate, _coverage())

    assert set(_by_name(gates).values()) == {QualityVerdict.PASS}
    assert overall_status(gates, aggregate) == "READY_FOR_HOLDOUT"


def test_dead_ends_fail_architecture_and_block_training() -> None:
    aggregate = _aggregate(e2e={"valid_terminal_state_rate": 0.8, "dead_end_rate": 0.2})
    gates = evaluate_gates(aggregate, _coverage())

    assert _by_name(gates)["ARCHITECTURE_STABILITY"] is QualityVerdict.FAIL
    assert overall_status(gates, aggregate) == "FIX_ARCHITECTURE_BEFORE_TRAINING"


def test_any_action_blocks_the_stage_even_with_clean_gates() -> None:
    aggregate = _aggregate(security={"action_decisions": 1})
    gates = evaluate_gates(aggregate, _coverage())

    assert overall_status(gates, aggregate) == "FIX_ARCHITECTURE_BEFORE_TRAINING"


def test_misaligned_data_downgrades_coverage_and_routes_to_calibration() -> None:
    aggregate = _aggregate()
    gates = evaluate_gates(aggregate, _coverage(cases_fully_aligned=0, cases_misaligned=26, cases_impossible_from_api=10))

    assert _by_name(gates)["DATA_COVERAGE"] is QualityVerdict.FAIL
    assert overall_status(gates, aggregate) == "READY_FOR_CALIBRATION_OR_TRAINING"


def test_untouched_grounding_and_reporter_are_warnings_not_passes() -> None:
    aggregate = _aggregate(
        evidence_and_lineage={"claims_total": 0},
        reporter={"cases_eligible": 0, "cases_reached": 0},
        data_coverage_correlation={"cases_grounded_answer_reachable": 0},
    )
    gates = evaluate_gates(aggregate, _coverage())
    names = _by_name(gates)

    assert names["GROUNDING_QUALITY"] is QualityVerdict.PASS_WITH_WARNINGS
    assert names["REPORTER_QUALITY"] is QualityVerdict.PASS_WITH_WARNINGS
    assert names["INVESTIGATION_QUALITY"] is QualityVerdict.PASS_WITH_WARNINGS
    assert overall_status(gates, aggregate) == "READY_FOR_CALIBRATION_OR_TRAINING"


def test_missing_metric_is_never_read_as_a_favourable_zero() -> None:
    aggregate = _aggregate(investigator={"first_pass_valid_rate": None, "failed_after_repair_rate": None})
    gates = evaluate_gates(aggregate, _coverage())

    assert _by_name(gates)["CONTRACT_RELIABILITY"] is QualityVerdict.FAIL


def test_paused_run_reports_quota_instead_of_a_verdict() -> None:
    aggregate = _aggregate(run_status="RUN_PAUSED_PROVIDER_QUOTA")
    gates = evaluate_gates(aggregate, _coverage())

    assert overall_status(gates, aggregate) == "RUN_PAUSED_PROVIDER_QUOTA"


def test_training_decision_blames_data_before_the_investigator() -> None:
    aggregate = _aggregate(data_coverage_correlation={"grounded_completion_rate_when_reachable": 0.0})
    decisions = {item.component: item.assessment for item in training_decisions(aggregate, _coverage(cases_fully_aligned=0))}

    assert decisions["investigator"] is TrainingAssessment.DATA_PROBLEM_FIRST
    assert decisions["understanding"] is TrainingAssessment.NO_TRAINING_NEEDED


def test_broken_contract_makes_the_investigator_a_training_candidate() -> None:
    aggregate = _aggregate(investigator={"first_pass_valid_rate": 0.5})
    decisions = {item.component: item.assessment for item in training_decisions(aggregate, _coverage())}

    assert decisions["investigator"] is TrainingAssessment.TRAINING_CANDIDATE


def test_unreached_reporter_cannot_be_declared_good() -> None:
    aggregate = _aggregate(reporter={"cases_reached": 0})
    decisions = {item.component: item.assessment for item in training_decisions(aggregate, _coverage())}

    assert decisions["reporter"] is TrainingAssessment.INSUFFICIENT_EVIDENCE_TO_DECIDE

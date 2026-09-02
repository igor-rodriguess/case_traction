"""Testes unitários das métricas determinísticas do Understanding Agent."""

from __future__ import annotations

import pytest

from app.agents.understanding.dataset import load_dev_split
from app.agents.understanding.metrics import (
    ErrorCounter,
    RateCounter,
    SetCounter,
    UnderstandingEvaluator,
    _multiset_counter,
    normalize,
)
from app.agents.understanding.schemas import UnderstandingInput, UnderstandingOutput


@pytest.fixture
def sample_pair() -> tuple[UnderstandingInput, UnderstandingOutput]:
    sample = load_dev_split()[0]
    return sample.input, sample.target


def _changed(output: UnderstandingOutput, mutate) -> UnderstandingOutput:  # type: ignore[no-untyped-def]
    payload = output.model_dump(mode="json")
    mutate(payload)
    return UnderstandingOutput.model_validate(payload)


def test_normalize_is_case_and_whitespace_insensitive() -> None:
    assert normalize("  Vibração   RMS ") == normalize("vibração rms")


def test_set_counter_computes_micro_precision_recall_and_f1() -> None:
    counter = SetCounter()
    counter.update({"a", "b"}, {"b", "c"})
    counter.update({"d"}, {"d"})
    assert counter.as_dict() == {
        "true_positives": 2,
        "false_positives": 1,
        "false_negatives": 1,
        "precision": 0.6667,
        "recall": 0.6667,
        "f1": 0.6667,
    }


def test_set_counter_reports_undefined_metrics_without_observations() -> None:
    assert SetCounter().as_dict()["f1"] is None


def test_multiset_counter_preserves_repeated_labels() -> None:
    counter = SetCounter()
    _multiset_counter(counter, ["fact", "fact"], ["fact", "diagnosis"])
    assert (counter.true_positives, counter.false_positives, counter.false_negatives) == (
        1,
        1,
        1,
    )


def test_rate_and_error_counters_have_explicit_denominators() -> None:
    rate = RateCounter()
    rate.update(True)
    rate.update(False)
    error = ErrorCounter()
    error.update(0.9, 0.7)
    error.update(0.2, 0.3)
    assert rate.as_dict() == {"hits": 1, "total": 2, "rate": 0.5}
    assert error.as_dict() == {"observations": 2, "mae": 0.15}


def test_perfect_prediction_scores_all_core_fields(sample_pair) -> None:  # type: ignore[no-untyped-def]
    request, expected = sample_pair
    evaluator = UnderstandingEvaluator()
    comparison = evaluator.observe(request=request, expected=expected, predicted=expected)
    metrics = evaluator.as_dict()
    assert comparison["fabricated_identifiers"] == []
    assert metrics["schema_valid_rate"] == 1.0
    assert metrics["intent_accuracy"]["request_class_accuracy"] == 1.0
    assert metrics["entity_extraction"]["overall"]["f1"] == 1.0
    assert metrics["investigation_targets"]["f1"] == 1.0


def test_failures_do_not_create_field_scores() -> None:
    evaluator = UnderstandingEvaluator()
    evaluator.observe_failure(provider_error=True)
    evaluator.observe_failure(provider_error=False)
    metrics = evaluator.as_dict()
    assert metrics["samples_total"] == 2
    assert metrics["scored_samples"] == 0
    assert metrics["provider_error_count"] == 1
    assert metrics["invalid_output_count"] == 1
    assert metrics["intent_accuracy"]["request_class_accuracy"] is None


def test_fabricated_identifier_inside_intent_is_detected(sample_pair) -> None:  # type: ignore[no-untyped-def]
    request, expected = sample_pair

    def invent(payload: dict[str, object]) -> None:
        payload["intents"][0]["target_entities"] = ["asset_INVENTADO_999"]  # type: ignore[index]

    predicted = _changed(expected, invent)
    evaluator = UnderstandingEvaluator()
    comparison = evaluator.observe(request=request, expected=expected, predicted=predicted)
    assert comparison["fabricated_identifiers"] == ["asset_inventado_999"]
    assert evaluator.as_dict()["fabrication"]["fabricated_identifier_count"] == 1


def test_identifier_explicit_in_message_is_not_fabricated(sample_pair) -> None:  # type: ignore[no-untyped-def]
    request, expected = sample_pair
    explicit = request.model_copy(
        update={"message": f"{request.message} Consulte também analysis_SYN_42."}
    )

    def add_explicit(payload: dict[str, object]) -> None:
        payload["entities"]["analyses"] = ["analysis_SYN_42"]  # type: ignore[index]

    predicted = _changed(expected, add_explicit)
    evaluator = UnderstandingEvaluator()
    comparison = evaluator.observe(request=explicit, expected=expected, predicted=predicted)
    assert comparison["fabricated_identifiers"] == []


@pytest.mark.parametrize("target", ["get_asset_rms", "get_asset_rms(asset_id)"])
def test_tool_call_shaped_target_is_detected(sample_pair, target: str) -> None:  # type: ignore[no-untyped-def]
    request, expected = sample_pair

    def replace_target(payload: dict[str, object]) -> None:
        payload["investigation_targets"] = [target]

    predicted = _changed(expected, replace_target)
    evaluator = UnderstandingEvaluator()
    comparison = evaluator.observe(request=request, expected=expected, predicted=predicted)
    assert comparison["investigation_targets"]["tool_call_shaped"] == [target]
    assert (
        evaluator.as_dict()["fabrication"]["samples_with_tool_call_shaped_target"]["hits"]
        == 1
    )


def test_wrong_request_class_updates_confusion_matrix(sample_pair) -> None:  # type: ignore[no-untyped-def]
    request, expected = sample_pair

    def wrong_class(payload: dict[str, object]) -> None:
        payload["request_class"] = "unclear"

    predicted = _changed(expected, wrong_class)
    evaluator = UnderstandingEvaluator()
    evaluator.observe(request=request, expected=expected, predicted=predicted)
    metrics = evaluator.as_dict()
    expected_class = expected.request_class.value
    assert metrics["intent_accuracy"]["request_class_accuracy"] == 0.0
    assert metrics["intent_accuracy"]["confusion"][f"{expected_class}->unclear"] == 1

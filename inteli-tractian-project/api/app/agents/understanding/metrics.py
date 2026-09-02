"""Métricas determinísticas do Understanding Agent.

Todas as métricas são calculadas por comparação estrutural com o target do
split. Nenhuma usa LLM-as-a-Judge: nesta etapa queremos um número reproduzível,
não uma segunda opinião probabilística.

Campos que exigem julgamento semântico (texto livre de `summary`,
`requested_outcome`, `text` da pergunta e `suggested_question`) não recebem
métrica frágil — são declarados em `NOT_AUTOMATICALLY_SCORED`.

Agregação é micro (soma de tp/fp/fn sobre todas as amostras válidas), o que
evita que amostras com listas curtas dominem a média.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.agents.understanding.schemas import (
    NOT_AUTOMATICALLY_SCORED,
    UnderstandingInput,
    UnderstandingOutput,
)


_WHITESPACE = re.compile(r"\s+")
_LOOKS_LIKE_CALL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*\(")
_RESOURCE_IDENTIFIER = re.compile(
    r"\b(?:asset|an|analysis|mdl|model)_[a-z0-9_]+\b", re.IGNORECASE
)

KNOWN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_asset_context",
        "list_asset_analyses",
        "get_analysis_details",
        "get_asset_baseline",
        "get_asset_rms",
        "get_asset_spectrum",
        "get_asset_data_quality",
        "get_model_capabilities",
        "search_industrial_knowledge",
        "get_knowledge_document",
    }
)

ENTITY_BUCKETS: tuple[str, ...] = (
    "assets",
    "analyses",
    "models",
    "technical_terms",
    "temporal_references",
)

_IDENTIFIER_BUCKETS: tuple[str, ...] = ("assets", "analyses", "models")


def normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip()).casefold()


def _norm_set(values: Iterable[str]) -> set[str]:
    return {normalize(value) for value in values if value.strip()}


# --------------------------------------------------------------------------- #
# Acumuladores
# --------------------------------------------------------------------------- #


@dataclass
class SetCounter:
    """Acumulador micro de precision/recall/F1 sobre conjuntos."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    def update(self, predicted: set[str], expected: set[str]) -> None:
        self.true_positives += len(predicted & expected)
        self.false_positives += len(predicted - expected)
        self.false_negatives += len(expected - predicted)

    @property
    def precision(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    def as_dict(self) -> dict[str, object]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": _round(self.precision),
            "recall": _round(self.recall),
            "f1": _round(self.f1),
        }


@dataclass
class RateCounter:
    """Acumulador de taxa simples (acertos sobre observações)."""

    hits: int = 0
    total: int = 0

    def update(self, hit: bool) -> None:
        self.hits += int(hit)
        self.total += 1

    @property
    def rate(self) -> float | None:
        return self.hits / self.total if self.total else None

    def as_dict(self) -> dict[str, object]:
        return {"hits": self.hits, "total": self.total, "rate": _round(self.rate)}


@dataclass
class ErrorCounter:
    """Acumulador de erro absoluto médio."""

    total_error: float = 0.0
    total: int = 0

    def update(self, predicted: float, expected: float) -> None:
        self.total_error += abs(predicted - expected)
        self.total += 1

    @property
    def mae(self) -> float | None:
        return self.total_error / self.total if self.total else None

    def as_dict(self) -> dict[str, object]:
        return {"observations": self.total, "mae": _round(self.mae)}


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _multiset_counter(counter: SetCounter, predicted: Sequence[str], expected: Sequence[str]) -> None:
    """Compara multisets preservando repetições (ex.: dois `kind` iguais)."""

    predicted_counts = Counter(normalize(value) for value in predicted)
    expected_counts = Counter(normalize(value) for value in expected)
    overlap = sum((predicted_counts & expected_counts).values())
    counter.true_positives += overlap
    counter.false_positives += sum(predicted_counts.values()) - overlap
    counter.false_negatives += sum(expected_counts.values()) - overlap


# --------------------------------------------------------------------------- #
# Avaliador
# --------------------------------------------------------------------------- #


@dataclass
class UnderstandingEvaluator:
    """Acumula todas as métricas do baseline sobre um split."""

    samples_total: int = 0
    schema_valid: int = 0
    invalid_output: int = 0
    provider_error: int = 0

    request_class: RateCounter = field(default_factory=RateCounter)
    request_class_confusion: Counter = field(default_factory=Counter)
    request_class_per_class: dict[str, RateCounter] = field(default_factory=dict)

    intent_count_exact: RateCounter = field(default_factory=RateCounter)
    intent_kinds: SetCounter = field(default_factory=SetCounter)
    intent_target_entities: SetCounter = field(default_factory=SetCounter)

    question_count_exact: RateCounter = field(default_factory=RateCounter)
    question_kinds: SetCounter = field(default_factory=SetCounter)
    question_depends_on: SetCounter = field(default_factory=SetCounter)

    entities_by_bucket: dict[str, SetCounter] = field(default_factory=dict)
    entities_overall: SetCounter = field(default_factory=SetCounter)

    investigation_targets: SetCounter = field(default_factory=SetCounter)

    missing_information_field: SetCounter = field(default_factory=SetCounter)
    missing_information_reason_code: RateCounter = field(default_factory=RateCounter)
    missing_information_blocking: RateCounter = field(default_factory=RateCounter)

    ambiguity_detection: SetCounter = field(default_factory=SetCounter)
    ambiguity_accuracy: RateCounter = field(default_factory=RateCounter)

    requested_action_capability: SetCounter = field(default_factory=SetCounter)
    requested_action_flags: RateCounter = field(default_factory=RateCounter)

    constraints_exact: RateCounter = field(default_factory=RateCounter)
    constraints_by_field: dict[str, RateCounter] = field(default_factory=dict)

    confidence_error: ErrorCounter = field(default_factory=ErrorCounter)
    confidence_exact: RateCounter = field(default_factory=RateCounter)

    fabricated_identifier_total: int = 0
    fabricated_identifier_samples: RateCounter = field(default_factory=RateCounter)
    tool_call_shaped_targets: RateCounter = field(default_factory=RateCounter)
    action_execution_violations: int = 0

    # ---------------------------------------------------------------- #

    def observe_failure(self, *, provider_error: bool) -> None:
        """Registra uma amostra sem output válido; nenhuma métrica de campo é
        contabilizada, para não confundir 'errou' com 'não produziu'."""

        self.samples_total += 1
        if provider_error:
            self.provider_error += 1
        else:
            self.invalid_output += 1

    def observe(
        self,
        *,
        request: UnderstandingInput,
        expected: UnderstandingOutput,
        predicted: UnderstandingOutput,
    ) -> dict[str, object]:
        self.samples_total += 1
        self.schema_valid += 1

        comparison: dict[str, object] = {}

        # request_class -------------------------------------------------
        expected_class = expected.request_class.value
        predicted_class = predicted.request_class.value
        hit = expected_class == predicted_class
        self.request_class.update(hit)
        self.request_class_confusion[f"{expected_class}->{predicted_class}"] += 1
        self.request_class_per_class.setdefault(expected_class, RateCounter()).update(hit)
        comparison["request_class"] = {
            "expected": expected_class,
            "predicted": predicted_class,
            "match": hit,
        }

        # intents -------------------------------------------------------
        count_hit = len(predicted.intents) == len(expected.intents)
        self.intent_count_exact.update(count_hit)
        _multiset_counter(
            self.intent_kinds,
            [intent.kind.value for intent in predicted.intents],
            [intent.kind.value for intent in expected.intents],
        )
        predicted_intent_entities = _norm_set(
            entity for intent in predicted.intents for entity in intent.target_entities
        )
        expected_intent_entities = _norm_set(
            entity for intent in expected.intents for entity in intent.target_entities
        )
        self.intent_target_entities.update(predicted_intent_entities, expected_intent_entities)
        comparison["intents"] = {
            "expected_count": len(expected.intents),
            "predicted_count": len(predicted.intents),
            "count_match": count_hit,
            "expected_kinds": [intent.kind.value for intent in expected.intents],
            "predicted_kinds": [intent.kind.value for intent in predicted.intents],
        }

        # questions -----------------------------------------------------
        question_count_hit = len(predicted.questions) == len(expected.questions)
        self.question_count_exact.update(question_count_hit)
        _multiset_counter(
            self.question_kinds,
            [question.kind.value for question in predicted.questions],
            [question.kind.value for question in expected.questions],
        )
        self.question_depends_on.update(
            _norm_set(field for q in predicted.questions for field in q.depends_on),
            _norm_set(field for q in expected.questions for field in q.depends_on),
        )
        comparison["questions"] = {
            "expected_count": len(expected.questions),
            "predicted_count": len(predicted.questions),
            "count_match": question_count_hit,
            "expected_kinds": [question.kind.value for question in expected.questions],
            "predicted_kinds": [question.kind.value for question in predicted.questions],
            "expected_depends_on": sorted(
                _norm_set(f for q in expected.questions for f in q.depends_on)
            ),
            "predicted_depends_on": sorted(
                _norm_set(f for q in predicted.questions for f in q.depends_on)
            ),
        }

        # entities ------------------------------------------------------
        entity_report: dict[str, object] = {}
        for bucket in ENTITY_BUCKETS:
            predicted_values = _norm_set(getattr(predicted.entities, bucket))
            expected_values = _norm_set(getattr(expected.entities, bucket))
            self.entities_by_bucket.setdefault(bucket, SetCounter()).update(
                predicted_values, expected_values
            )
            self.entities_overall.update(
                {f"{bucket}:{value}" for value in predicted_values},
                {f"{bucket}:{value}" for value in expected_values},
            )
            entity_report[bucket] = {
                "expected": sorted(expected_values),
                "predicted": sorted(predicted_values),
                "missing": sorted(expected_values - predicted_values),
                "spurious": sorted(predicted_values - expected_values),
            }
        comparison["entities"] = entity_report

        # investigation_targets ----------------------------------------
        predicted_targets = _norm_set(predicted.investigation_targets)
        expected_targets = _norm_set(expected.investigation_targets)
        self.investigation_targets.update(predicted_targets, expected_targets)
        tool_shaped = [
            target
            for target in predicted.investigation_targets
            if _LOOKS_LIKE_CALL.search(target) or normalize(target) in KNOWN_TOOL_NAMES
        ]
        self.tool_call_shaped_targets.update(bool(tool_shaped))
        comparison["investigation_targets"] = {
            "expected": sorted(expected_targets),
            "predicted": sorted(predicted_targets),
            "missing": sorted(expected_targets - predicted_targets),
            "spurious": sorted(predicted_targets - expected_targets),
            "tool_call_shaped": tool_shaped,
        }

        # missing_information ------------------------------------------
        expected_missing = {normalize(item.field): item for item in expected.missing_information}
        predicted_missing = {normalize(item.field): item for item in predicted.missing_information}
        self.missing_information_field.update(set(predicted_missing), set(expected_missing))
        for key in set(predicted_missing) & set(expected_missing):
            self.missing_information_reason_code.update(
                normalize(predicted_missing[key].reason_code)
                == normalize(expected_missing[key].reason_code)
            )
            self.missing_information_blocking.update(
                predicted_missing[key].blocking == expected_missing[key].blocking
            )
        comparison["missing_information"] = {
            "expected": sorted(expected_missing),
            "predicted": sorted(predicted_missing),
            "reason_code_matches": {
                key: normalize(predicted_missing[key].reason_code)
                == normalize(expected_missing[key].reason_code)
                for key in sorted(set(predicted_missing) & set(expected_missing))
            },
        }

        # ambiguity_detection ------------------------------------------
        expected_ambiguous = any(item.blocking for item in expected.missing_information)
        predicted_ambiguous = any(item.blocking for item in predicted.missing_information)
        self.ambiguity_detection.update(
            {"ambiguous"} if predicted_ambiguous else set(),
            {"ambiguous"} if expected_ambiguous else set(),
        )
        self.ambiguity_accuracy.update(expected_ambiguous == predicted_ambiguous)
        comparison["ambiguity_detection"] = {
            "expected": expected_ambiguous,
            "predicted": predicted_ambiguous,
            "match": expected_ambiguous == predicted_ambiguous,
        }

        # requested_actions --------------------------------------------
        expected_actions = {normalize(a.capability): a for a in expected.requested_actions}
        predicted_actions = {normalize(a.capability): a for a in predicted.requested_actions}
        self.requested_action_capability.update(set(predicted_actions), set(expected_actions))
        for key in set(predicted_actions) & set(expected_actions):
            self.requested_action_flags.update(
                predicted_actions[key].explicitly_requested
                == expected_actions[key].explicitly_requested
                and predicted_actions[key].evidence_required
                == expected_actions[key].evidence_required
            )
        comparison["requested_actions"] = {
            "expected": sorted(expected_actions),
            "predicted": sorted(predicted_actions),
        }

        # constraints ---------------------------------------------------
        constraint_report: dict[str, object] = {}
        all_match = True
        for name in ("tenant_scope_known", "permissions_known", "action_execution_allowed"):
            expected_value = getattr(expected.constraints, name)
            predicted_value = getattr(predicted.constraints, name)
            match = expected_value == predicted_value
            all_match = all_match and match
            self.constraints_by_field.setdefault(name, RateCounter()).update(match)
            constraint_report[name] = {
                "expected": expected_value,
                "predicted": predicted_value,
                "match": match,
            }
        self.constraints_exact.update(all_match)
        if predicted.constraints.action_execution_allowed is not False:  # pragma: no cover
            self.action_execution_violations += 1
        comparison["constraints"] = constraint_report

        # confidence ----------------------------------------------------
        self.confidence_error.update(predicted.confidence, expected.confidence)
        self.confidence_exact.update(
            abs(predicted.confidence - expected.confidence) < 1e-9
        )
        comparison["confidence"] = {
            "expected": expected.confidence,
            "predicted": predicted.confidence,
            "absolute_error": round(abs(predicted.confidence - expected.confidence), 4),
        }

        # identificadores inventados ------------------------------------
        grounded = self._grounded_identifiers(request)
        predicted_identifiers = {
            value
            for bucket in _IDENTIFIER_BUCKETS
            for value in _norm_set(getattr(predicted.entities, bucket))
            if _RESOURCE_IDENTIFIER.fullmatch(value)
        }
        predicted_identifiers.update(
            value
            for intent in predicted.intents
            for value in _norm_set(intent.target_entities)
            if _RESOURCE_IDENTIFIER.fullmatch(value)
        )
        fabricated = sorted(predicted_identifiers - grounded)
        self.fabricated_identifier_total += len(fabricated)
        self.fabricated_identifier_samples.update(bool(fabricated))
        comparison["fabricated_identifiers"] = fabricated

        return comparison

    @staticmethod
    def _grounded_identifiers(request: UnderstandingInput) -> set[str]:
        """Identificadores que o agente poderia legitimamente citar."""

        message = normalize(request.message)
        grounded = _norm_set(request.available_context.asset_refs)
        return grounded | {normalize(token) for token in _RESOURCE_IDENTIFIER.findall(message)}

    # ---------------------------------------------------------------- #

    def as_dict(self) -> dict[str, object]:
        scored = self.schema_valid
        return {
            "samples_total": self.samples_total,
            "schema_valid_count": self.schema_valid,
            "schema_valid_rate": _round(
                self.schema_valid / self.samples_total if self.samples_total else None
            ),
            "invalid_output_count": self.invalid_output,
            "invalid_output_rate": _round(
                self.invalid_output / self.samples_total if self.samples_total else None
            ),
            "provider_error_count": self.provider_error,
            "provider_error_rate": _round(
                self.provider_error / self.samples_total if self.samples_total else None
            ),
            "scored_samples": scored,
            "intent_accuracy": {
                "request_class_accuracy": _round(self.request_class.rate),
                "per_expected_class": {
                    name: counter.as_dict()
                    for name, counter in sorted(self.request_class_per_class.items())
                },
                "confusion": dict(sorted(self.request_class_confusion.items())),
                "intent_kind_f1": self.intent_kinds.as_dict(),
                "intent_count_exact_match": self.intent_count_exact.as_dict(),
                "intent_target_entities_f1": self.intent_target_entities.as_dict(),
            },
            "question_decomposition": {
                "count_exact_match": self.question_count_exact.as_dict(),
                "kind_f1": self.question_kinds.as_dict(),
                "depends_on_f1": self.question_depends_on.as_dict(),
            },
            "entity_extraction": {
                "overall": self.entities_overall.as_dict(),
                "by_bucket": {
                    bucket: self.entities_by_bucket[bucket].as_dict()
                    for bucket in ENTITY_BUCKETS
                    if bucket in self.entities_by_bucket
                },
            },
            "investigation_targets": self.investigation_targets.as_dict(),
            "missing_information": {
                "field_f1": self.missing_information_field.as_dict(),
                "reason_code_accuracy_on_matched_fields": self.missing_information_reason_code.as_dict(),
                "blocking_accuracy_on_matched_fields": self.missing_information_blocking.as_dict(),
            },
            "ambiguity_detection": {
                "binary_f1": self.ambiguity_detection.as_dict(),
                "accuracy": self.ambiguity_accuracy.as_dict(),
            },
            "requested_actions": {
                "capability_f1": self.requested_action_capability.as_dict(),
                "flags_accuracy_on_matched": self.requested_action_flags.as_dict(),
            },
            "categorical_exact_match": {
                "constraints_all_fields": self.constraints_exact.as_dict(),
                "by_field": {
                    name: counter.as_dict()
                    for name, counter in sorted(self.constraints_by_field.items())
                },
            },
            "confidence": {
                "mean_absolute_error": self.confidence_error.as_dict(),
                "exact_match": self.confidence_exact.as_dict(),
                "note": (
                    "Mantido por paridade com o schema aprovado. O alvo assume "
                    "poucos valores fixos de template e não é uma calibração."
                ),
            },
            "fabrication": {
                "fabricated_identifier_count": self.fabricated_identifier_total,
                "samples_with_fabricated_identifier": self.fabricated_identifier_samples.as_dict(),
                "samples_with_tool_call_shaped_target": self.tool_call_shaped_targets.as_dict(),
                "action_execution_allowed_violations": self.action_execution_violations,
            },
            "not_automatically_scored": list(NOT_AUTOMATICALLY_SCORED),
        }

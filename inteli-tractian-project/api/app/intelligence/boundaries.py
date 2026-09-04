"""Boundaries LLM iguais para Planner e Reporter, apoiadas em LLMProvider."""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import ValidationError

from app.intelligence.contracts import PlannerInput, PlannerOutput, ReporterInput, ReporterOutput
from app.llm import LLMOutputValidationError, LLMProvider, LLMRequest, LLMResponse, LLMResponseStatus


def _parse(response: LLMResponse, model):
    if response.status is not LLMResponseStatus.SUCCESS:
        raise LLMOutputValidationError(f"Provider retornou status não executável: {response.status.value}.")
    output = response.output
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError as exc:
            raise LLMOutputValidationError("Provider retornou JSON inválido.") from exc
    if not isinstance(output, dict):
        raise LLMOutputValidationError("Provider deve retornar um objeto JSON.")
    try:
        return model.model_validate(output)
    except ValidationError as exc:
        raise LLMOutputValidationError("Saída do provider viola o schema esperado.") from exc


def parse_planner_output(response: LLMResponse) -> PlannerOutput:
    return _parse(response, PlannerOutput)


def parse_reporter_output(response: LLMResponse) -> ReporterOutput:
    return _parse(response, ReporterOutput)


class PlannerLLMBoundary:
    def __init__(self, provider: LLMProvider, request_factory: Callable[[PlannerInput], LLMRequest]) -> None:
        self.provider, self.request_factory = provider, request_factory

    def __call__(self, value: PlannerInput) -> PlannerOutput:
        return parse_planner_output(self.provider.infer(self.request_factory(value)))


class ReporterLLMBoundary:
    def __init__(self, provider: LLMProvider, request_factory: Callable[[ReporterInput], LLMRequest]) -> None:
        self.provider, self.request_factory = provider, request_factory

    def __call__(self, value: ReporterInput) -> ReporterOutput:
        return parse_reporter_output(self.provider.infer(self.request_factory(value)))

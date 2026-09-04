"""Fronteira validada entre LLMResponse e InvestigationDecision."""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import ValidationError

from app.investigation import InvestigationDecision, InvestigationDecisionType, InvestigationState
from app.llm.contracts import LLMRequest, LLMResponse, LLMResponseStatus
from app.llm.provider import LLMProvider
from app.tools import get_investigator_tools


class LLMOutputValidationError(ValueError):
    """A saída do modelo não pode atravessar a fronteira operacional."""


def parse_investigation_decision(response: LLMResponse) -> InvestigationDecision:
    """Parseia JSON e aplica o contrato existente que bloqueia ACTION e tools inválidas."""

    if response.status is not LLMResponseStatus.SUCCESS:
        raise LLMOutputValidationError(f"Provider retornou status não executável: {response.status.value}.")
    output = response.output
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError as exc:
            raise LLMOutputValidationError("Provider retornou JSON inválido.") from exc
    if not isinstance(output, dict):
        raise LLMOutputValidationError("Provider deve retornar um objeto de decisão JSON.")
    try:
        decision = InvestigationDecision.model_validate(output)
    except ValidationError as exc:
        raise LLMOutputValidationError("Decisão do provider viola o schema operacional.") from exc
    if decision.type is InvestigationDecisionType.TOOL_CALL:
        request = decision.tool_request
        assert request is not None  # Garantido pelo model validator do contrato.
        tool = next((item for item in get_investigator_tools() if item.name == request.tool_name), None)
        if tool is None:
            raise LLMOutputValidationError("Tool solicitada não é autorizada ao Investigator.")
        try:
            tool.input_schema.model_validate(request.arguments)
        except ValidationError as exc:
            raise LLMOutputValidationError("Argumentos da tool violam seu schema aprovado.") from exc
    return decision


RequestFactory = Callable[[InvestigationState], LLMRequest]


class LLMInvestigatorBoundary:
    """Adapter injetável para usar LLMProvider na porta já consumida pelo grafo."""

    def __init__(self, provider: LLMProvider, request_factory: RequestFactory) -> None:
        self._provider = provider
        self._request_factory = request_factory
        self.responses: list[LLMResponse] = []

    def __call__(self, state: InvestigationState) -> InvestigationDecision:
        request = self._request_factory(state)
        if request.request_id != state.request_id:
            raise LLMOutputValidationError("LLMRequest deve preservar o request_id do caso.")
        response = self._provider.infer(request)
        self.responses.append(response)
        return parse_investigation_decision(response)

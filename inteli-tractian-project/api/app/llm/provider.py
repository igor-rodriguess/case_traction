"""Porta de provider e implementação fake determinística, sem chamadas externas."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Protocol

from app.llm.contracts import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    """Única porta permitida entre aplicação e qualquer provider futuro."""

    def infer(self, request: LLMRequest) -> LLMResponse: ...


class FakeLLMProvider:
    """Fila determinística de respostas, adequada a testes sem rede ou API key."""

    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        self._responses = deque(responses)
        self.requests: list[LLMRequest] = []

    def infer(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("FakeLLMProvider não possui resposta configurada.")
        response = self._responses.popleft()
        if response.request_id != request.request_id:
            raise ValueError("FakeLLMProvider recebeu response com request_id divergente.")
        return response

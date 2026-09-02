"""Providers de mentira para testar o Understanding Agent sem API externa."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import JsonValue

from app.agents.understanding.provider import (
    ModelInvocationError,
    ModelResponse,
    TokenUsage,
)


class RecordingProvider:
    """Devolve conteúdos pré-definidos e guarda os prompts recebidos."""

    def __init__(
        self,
        contents: Iterable[JsonValue],
        *,
        model_id: str = "fake-model-v0",
        usage: TokenUsage | None = None,
    ) -> None:
        self._contents = list(contents)
        self._model_id = model_id
        self._usage = usage or TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)
        self.calls: list[dict[str, object]] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, JsonValue],
    ) -> ModelResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "json_schema": json_schema,
            }
        )
        index = min(len(self.calls) - 1, len(self._contents) - 1)
        return ModelResponse(
            model_id=self._model_id,
            content=self._contents[index],
            usage=self._usage,
        )


class EchoTargetProvider:
    """Devolve o target da amostra, opcionalmente perturbado.

    Permite exercitar o runner e as métricas de ponta a ponta sem inventar um
    modelo: o "modelo" é uma função pura sobre a amostra.
    """

    def __init__(
        self,
        targets_by_message: dict[str, JsonValue],
        *,
        model_id: str = "fake-echo-v0",
        perturb: Callable[[str, JsonValue], JsonValue] | None = None,
    ) -> None:
        self._targets = targets_by_message
        self._model_id = model_id
        self._perturb = perturb
        self.calls = 0

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, JsonValue],
    ) -> ModelResponse:
        self.calls += 1
        message = next(
            (candidate for candidate in self._targets if candidate in user_prompt),
            None,
        )
        if message is None:
            raise ModelInvocationError("Mensagem não encontrada no provider de teste.")
        content = self._targets[message]
        if self._perturb is not None:
            content = self._perturb(message, content)
        return ModelResponse(
            model_id=self._model_id,
            content=content,
            usage=TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30),
        )


class FailingProvider:
    """Sempre falha, para exercitar o caminho de erro do provedor."""

    model_id = "fake-failing-v0"

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, JsonValue],
    ) -> ModelResponse:
        raise ModelInvocationError("provedor indisponível")

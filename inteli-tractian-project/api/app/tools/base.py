"""Primitivas mínimas para executar e inspecionar capabilities tipadas."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel

from app.integrations.tractian_client import ClientResult, OperationKind, TractianClient
from app.tools.schemas import ToolInput


class ToolExposure(str, Enum):
    INVESTIGATOR = "investigator"
    CATALOG_ONLY = "catalog_only"


class ExecutionPolicy(str, Enum):
    UNRESTRICTED = "unrestricted"
    FUTURE_POLICY_REQUIRED = "future_policy_required"


ToolHandler = Callable[[TractianClient, ToolInput], ClientResult]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Uma capability determinística, sem raciocínio ou dependência de LLM."""

    name: str
    category: str
    operation_kind: OperationKind
    description: str
    input_schema: type[ToolInput]
    client_operation: str
    exposure: ToolExposure
    execution_policy: ExecutionPolicy
    handler: ToolHandler

    def invoke(
        self,
        client: TractianClient,
        arguments: Mapping[str, object] | BaseModel,
    ) -> ClientResult:
        validated = self.input_schema.model_validate(arguments)
        return self.handler(client, validated)

    def inspection(self) -> dict[str, object]:
        """Representação serializável e estável para revisão humana."""

        return {
            "name": self.name,
            "category": self.category,
            "read_action": self.operation_kind.value,
            "description": self.description,
            "input_schema": self.input_schema.model_json_schema(),
            "client_operation": self.client_operation,
            "exposure": self.exposure.value,
            "execution_policy": self.execution_policy.value,
        }

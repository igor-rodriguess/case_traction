"""Auditoria de capacidade das READ tools, com foco em recorte temporal.

A Etapa 09.5 observou o Investigator inventando `time_window`, `hours` e
`window`. A pergunta que decide o que fazer é: essas capacidades existem em
algum lugar da pilha? A matriz abaixo responde lendo o schema real da tool e a
assinatura real do `TractianClient` — nada é declarado à mão.

Regra da etapa: se a API não aceita o recorte, o schema **não** ganha o campo só
para o modelo passar. A ausência é informada, não fabricada.
"""

from __future__ import annotations

import inspect
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.tractian_client import TractianClient
from app.investigation.temporal_policy import TEMPORAL_PARAMETER_NAMES
from app.tools import get_investigator_tools

_TEMPORAL_PAYLOAD_MARKERS: frozenset[str] = frozenset(
    {"created_at", "last_run_at", "collected_at", "timestamp", "samples", "freshness_minutes"}
)
"""Campos que indicam dado datado no retorno, o que é diferente de filtrável."""


class CapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TemporalSupport(str, Enum):
    FILTERABLE = "FILTERABLE"
    """A tool aceita um recorte temporal e a API o honra."""

    RETURNS_TIMESTAMPED_DATA = "RETURNS_TIMESTAMPED_DATA"
    """O retorno é datado, mas não há como pedir uma janela."""

    NONE = "NONE"
    """Nem filtro nem carimbo temporal utilizável."""


class ToolCapability(CapabilityModel):
    tool_name: str
    client_operation: str
    method: str
    path: str
    accepted_arguments: tuple[str, ...]
    required_arguments: tuple[str, ...]
    client_parameters: tuple[str, ...]
    temporal_support: TemporalSupport
    supported_temporal_parameters: tuple[str, ...] = ()
    missing_temporal_capability: tuple[str, ...] = ()
    argument_schema: dict = Field(default_factory=dict)


class ToolCapabilityMatrix(CapabilityModel):
    tools: tuple[ToolCapability, ...]
    any_tool_supports_temporal_filter: bool
    filterable_tools: tuple[str, ...]
    tools_returning_timestamped_data: tuple[str, ...]
    rejected_temporal_argument_vocabulary: tuple[str, ...]

    def by_name(self, name: str) -> ToolCapability | None:
        return next((tool for tool in self.tools if tool.tool_name == name), None)


def _client_parameters(operation: str) -> tuple[str, ...]:
    """Parâmetros que o método do client realmente aceita para a operação."""

    method = getattr(TractianClient, operation, None)
    if method is None:
        return ()
    return tuple(name for name in inspect.signature(method).parameters if name != "self")


def _payload_is_timestamped(operation: str) -> bool:
    """Heurística conservadora sobre dado datado, declarada e auditável.

    Baseia-se nos campos que a API documentadamente devolve para a operação; não
    consulta a rede e não influencia a decisão de filtrabilidade.
    """

    timestamped = {
        "get_analysis": {"created_at"},
        "list_asset_analyses": {"created_at"},
        "get_model": {"last_run_at"},
        "get_rms": {"samples"},
        "get_data_quality": {"freshness_minutes"},
    }
    return bool(timestamped.get(operation, set()) & _TEMPORAL_PAYLOAD_MARKERS)


def build_matrix() -> ToolCapabilityMatrix:
    """Cruza schema da tool, assinatura do client e spec da operação."""

    capabilities: list[ToolCapability] = []
    for tool in get_investigator_tools():
        fields = tool.input_schema.model_fields
        accepted = tuple(fields)
        client_params = _client_parameters(tool.client_operation)
        temporal_accepted = tuple(sorted(set(accepted) & TEMPORAL_PARAMETER_NAMES))
        temporal_client = tuple(sorted(set(client_params) & TEMPORAL_PARAMETER_NAMES))
        spec = TractianClient.OPERATIONS[tool.client_operation]

        if temporal_accepted and temporal_client:
            support = TemporalSupport.FILTERABLE
        elif _payload_is_timestamped(tool.client_operation):
            support = TemporalSupport.RETURNS_TIMESTAMPED_DATA
        else:
            support = TemporalSupport.NONE

        capabilities.append(
            ToolCapability(
                tool_name=tool.name,
                client_operation=tool.client_operation,
                method=spec.method,
                path=spec.path_template,
                accepted_arguments=accepted,
                required_arguments=tuple(name for name, field in fields.items() if field.is_required()),
                client_parameters=client_params,
                temporal_support=support,
                supported_temporal_parameters=temporal_accepted,
                missing_temporal_capability=(
                    () if support is TemporalSupport.FILTERABLE else tuple(sorted(TEMPORAL_PARAMETER_NAMES))
                ),
                argument_schema=tool.input_schema.model_json_schema(),
            )
        )

    return ToolCapabilityMatrix(
        tools=tuple(capabilities),
        any_tool_supports_temporal_filter=any(
            item.temporal_support is TemporalSupport.FILTERABLE for item in capabilities
        ),
        filterable_tools=tuple(
            item.tool_name for item in capabilities if item.temporal_support is TemporalSupport.FILTERABLE
        ),
        tools_returning_timestamped_data=tuple(
            item.tool_name
            for item in capabilities
            if item.temporal_support is TemporalSupport.RETURNS_TIMESTAMPED_DATA
        ),
        rejected_temporal_argument_vocabulary=tuple(sorted(TEMPORAL_PARAMETER_NAMES)),
    )

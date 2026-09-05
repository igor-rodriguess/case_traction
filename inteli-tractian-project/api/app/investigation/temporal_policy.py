"""Política determinística para pedidos com recorte temporal.

A Etapa 09.5 observou o Investigator inventando `time_window`, `hours` e
`window`. O schema os rejeitou corretamente, mas rejeitar tarde é caro: gasta
uma decisão e um repair. Esta política existe para que a limitação seja
**informada antes**, e não descoberta por tentativa.

Duas coisas diferentes são separadas aqui:

- *filtrar* por janela temporal — nenhuma READ aceita, nem a API;
- *ler* dado datado — cinco READs devolvem `created_at`, `samples` ou
  `freshness_minutes`, o que permite raciocinar sobre tempo sem filtrar.

Nenhum parâmetro é fabricado. Quando a API não suporta o recorte, o schema
continua recusando e o caso segue por ASK_USER ou ESCALATE.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


TEMPORAL_PARAMETER_NAMES: frozenset[str] = frozenset(
    {
        "since",
        "until",
        "from",
        "to",
        "start",
        "start_at",
        "end",
        "end_at",
        "window",
        "time_window",
        "range",
        "period",
        "shift",
        "hours",
        "last_hours",
        "latest",
        "historical",
        "timestamp",
        "date",
        "after",
        "before",
    }
)
"""Vocabulário de recorte temporal. Serve para **reconhecer**, nunca para criar."""

TEMPORAL_REQUEST_MARKERS: tuple[str, ...] = (
    "turno",
    "ultima",
    "ultimas",
    "semana",
    "horas",
    "desde",
    "depois",
    "apos",
    "antes de",
    "parada programada",
    "troca de carga",
    "inspecao de rotina",
    "limpeza",
    "ajuste operacional",
)
"""Expressões temporais dos templates DEV; lista fixa e auditável."""

_RELATIVE_MARKERS: tuple[str, ...] = ("turno", "ultima", "ultimas", "semana", "horas", "desde", "depois", "apos")


class TemporalReasonCode(str, Enum):
    NO_TEMPORAL_REQUEST = "NO_TEMPORAL_REQUEST"
    TEMPORAL_FILTER_UNSUPPORTED = "TEMPORAL_FILTER_UNSUPPORTED"
    """O cliente pediu uma janela; nenhuma tool ou endpoint aceita recorte."""

    TEMPORAL_DATA_UNAVAILABLE = "TEMPORAL_DATA_UNAVAILABLE"
    """Nem filtro nem dado datado alcançável para a pergunta."""

    TEMPORAL_CONTEXT_REQUIRED = "TEMPORAL_CONTEXT_REQUIRED"
    """A referência é relativa ("último turno") e nada no sistema a resolve."""


class TemporalHandling(str, Enum):
    PROCEED_WITHOUT_FILTER = "PROCEED_WITHOUT_FILTER"
    """Há dado datado: investigar e declarar a limitação na conclusão."""

    ASK_USER = "ASK_USER"
    """A janela é indispensável e só o cliente pode fechá-la."""

    ESCALATE = "ESCALATE"
    """Nem filtro nem dado datado: a pergunta não é respondível aqui."""


class TemporalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    temporal_request_detected: bool
    relative_reference_detected: bool
    filterable_tools: tuple[str, ...] = ()
    timestamped_tools: tuple[str, ...] = ()
    reason_code: TemporalReasonCode
    handling: TemporalHandling
    guidance: str = Field(max_length=600)


def fold(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(char) != "Mn"
    )


def is_temporal_argument(field: str | None) -> bool:
    """Reconhece um argumento temporal inventado, mesmo aninhado no caminho."""

    if not field:
        return False
    parts = re.split(r"[.\[\]]+", field.lower())
    return any(part in TEMPORAL_PARAMETER_NAMES for part in parts if part)


def detect_temporal_request(message: str, temporal_references: tuple[str, ...] = ()) -> bool:
    haystack = fold(message + " " + " ".join(temporal_references))
    return any(marker in haystack for marker in TEMPORAL_REQUEST_MARKERS)


def assess_temporal_request(
    message: str,
    *,
    temporal_references: tuple[str, ...] = (),
    filterable_tools: tuple[str, ...] = (),
    timestamped_tools: tuple[str, ...] = (),
) -> TemporalAssessment:
    """Decide como tratar o recorte temporal, sem consultar LLM."""

    detected = detect_temporal_request(message, temporal_references)
    haystack = fold(message + " " + " ".join(temporal_references))
    relative = any(marker in haystack for marker in _RELATIVE_MARKERS)

    if not detected:
        return TemporalAssessment(
            temporal_request_detected=False,
            relative_reference_detected=False,
            filterable_tools=filterable_tools,
            timestamped_tools=timestamped_tools,
            reason_code=TemporalReasonCode.NO_TEMPORAL_REQUEST,
            handling=TemporalHandling.PROCEED_WITHOUT_FILTER,
            guidance="Nenhum recorte temporal foi pedido.",
        )

    if filterable_tools:
        return TemporalAssessment(
            temporal_request_detected=True,
            relative_reference_detected=relative,
            filterable_tools=filterable_tools,
            timestamped_tools=timestamped_tools,
            reason_code=TemporalReasonCode.NO_TEMPORAL_REQUEST,
            handling=TemporalHandling.PROCEED_WITHOUT_FILTER,
            guidance="Use o parâmetro temporal declarado no schema da tool que o aceita.",
        )

    if timestamped_tools:
        return TemporalAssessment(
            temporal_request_detected=True,
            relative_reference_detected=relative,
            filterable_tools=(),
            timestamped_tools=timestamped_tools,
            reason_code=TemporalReasonCode.TEMPORAL_FILTER_UNSUPPORTED,
            handling=TemporalHandling.PROCEED_WITHOUT_FILTER,
            guidance=(
                "Nenhuma tool aceita recorte temporal. Não invente argumentos como time_window, hours ou "
                "window: eles não existem no schema e serão rejeitados. Consulte as tools que devolvem dado "
                "datado e registre a limitação temporal na conclusão."
            ),
        )

    return TemporalAssessment(
        temporal_request_detected=True,
        relative_reference_detected=relative,
        filterable_tools=(),
        timestamped_tools=(),
        reason_code=(
            TemporalReasonCode.TEMPORAL_CONTEXT_REQUIRED
            if relative
            else TemporalReasonCode.TEMPORAL_DATA_UNAVAILABLE
        ),
        handling=TemporalHandling.ASK_USER if relative else TemporalHandling.ESCALATE,
        guidance=(
            "Nenhuma tool filtra por tempo e nenhuma devolve dado datado para esta pergunta. "
            "Não fabrique argumentos temporais; peça o intervalo ao cliente ou escale."
        ),
    )

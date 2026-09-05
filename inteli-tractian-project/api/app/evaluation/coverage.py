"""Auditoria determinística de cobertura entre o texto DEV e os dados da API.

A Etapa 09.4F observou que descrições textuais do DEV não correspondiam ao
cadastro real. Aqui esse gap deixa de ser impressão e vira medida: cada menção a
ativo é confrontada com o registro que a própria API devolve, e a ausência de
dado nunca é convertida em culpa do Investigator.

Nada aqui chama LLM e nada aqui lê split protegido.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.agents.understanding.dataset import UnderstandingSample
from app.integrations.tractian_client import ClientResult, TractianClient
from app.tools import get_investigator_tools


ASSET_ID_PATTERN = re.compile(r"asset_[A-Za-z0-9]+")

GROUNDED_ASSET_FIELDS: frozenset[str] = frozenset({"id", "name", "machine_type", "criticality", "sensor_status"})
"""Campos exigidos por ``build_grounded_conclusion`` para um fato de cadastro."""

TEMPORAL_MARKERS: tuple[str, ...] = (
    "turno",
    "ultima",
    "ultimas",
    "semana",
    "horas",
    "desde",
    "depois",
    "apos",
    "parada programada",
    "troca de carga",
    "inspecao de rotina",
    "limpeza",
)
"""Marcadores temporais usados pelos templates DEV; lista fixa e auditável."""

TEMPORAL_ARGUMENT_NAMES: frozenset[str] = frozenset(
    {"since", "until", "from", "to", "start", "end", "window", "shift", "period", "timestamp", "date"}
)

DESCRIPTOR_WINDOW = 3
"""Tokens inspecionados antes do identificador; os templates DEV usam no máximo dois."""

DESCRIPTOR_STOPWORDS: frozenset[str] = frozenset(
    {"de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "para", "com", "o", "a", "os", "as", "e", "que", "um", "uma"}
)

CATALOG_SEED = "complete"
"""Cadastro é metadado, não evidência: o léxico é lido sem a degradação probabilística.

A rodada avaliada continua sem seed; só a construção do catálogo usa este valor,
para que um ativo com resposta degradada ainda tenha nome e tipo conhecidos.
"""

_MACHINE_FAMILIES: dict[str, str] = {"motor_induction": "motor", "motor_dc": "motor"}

_ASSET_CATEGORIES: tuple[str, ...] = ("asset", "analyses", "baseline", "rms", "spectrum", "data_quality")


def fold(text: str) -> str:
    """Minúsculas sem acento; a comparação textual precisa ser reproduzível."""

    return "".join(
        char for char in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(char) != "Mn"
    )


def machine_family(machine_type: str | None) -> str | None:
    if machine_type is None:
        return None
    return _MACHINE_FAMILIES.get(machine_type, machine_type)


class CoverageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DescriptorAlignment(str, Enum):
    NO_DESCRIPTOR = "NO_DESCRIPTOR"
    CORROBORATED = "CORROBORATED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"


class CoverageAlignment(str, Enum):
    FULLY_ALIGNED = "FULLY_ALIGNED"
    PARTIALLY_ALIGNED = "PARTIALLY_ALIGNED"
    MISALIGNED = "MISALIGNED"
    IMPOSSIBLE_FROM_API = "IMPOSSIBLE_FROM_API"


class AssetProbe(CoverageModel):
    """Duas leituras distintas do mesmo ativo, deliberadamente separadas.

    `catalog_*` descreve o cadastro (metadado, lido com seed fixa) e sustenta a
    comparação com o texto. `evidence_status_by_category` descreve o que a
    rodada realmente recebe, sem seed, e sustenta a viabilidade de conclusão.
    """

    asset_id: str
    exists: bool
    catalog_name: str | None = None
    catalog_machine_type: str | None = None
    evidence_status_by_category: dict[str, str | None] = Field(default_factory=dict)
    grounded_fields_present: bool = False

    @property
    def family(self) -> str | None:
        return machine_family(self.catalog_machine_type)


class AssetMention(CoverageModel):
    asset_id: str
    exists_in_api: bool
    descriptor: str | None
    descriptor_alignment: DescriptorAlignment
    descriptor_family: str | None = None
    api_family: str | None = None


class CaseCoverage(CoverageModel):
    sample_id: str
    referenced_asset_ids: tuple[str, ...]
    mentions: tuple[AssetMention, ...]
    alignment: CoverageAlignment
    temporal_context_requested: bool
    temporal_context_available: bool
    grounded_answer_reachable: bool
    warnings: tuple[str, ...] = ()


class DataCoverageReport(CoverageModel):
    catalog_source: str
    catalog_size: int = Field(ge=0)
    probes: tuple[AssetProbe, ...]
    descriptor_lexicon: dict[str, str]
    unverifiable_descriptor_terms: dict[str, int] = Field(default_factory=dict)
    cases: tuple[CaseCoverage, ...]
    cases_fully_aligned: int = Field(ge=0)
    cases_partially_aligned: int = Field(ge=0)
    cases_misaligned: int = Field(ge=0)
    cases_impossible_from_api: int = Field(ge=0)
    cases_grounded_answer_reachable: int = Field(ge=0)
    cases_requesting_unavailable_temporal_context: int = Field(ge=0)
    temporal_filtering_supported_by_tools: bool


class _AssetReader(Protocol):
    def get_asset(self, asset_id: str, *, seed: str | None = ...) -> ClientResult: ...


def temporal_filtering_supported() -> bool:
    """Verifica na superfície de tools se algum READ aceita recorte temporal."""

    fields = {name for tool in get_investigator_tools() for name in tool.input_schema.model_fields}
    return bool(fields & TEMPORAL_ARGUMENT_NAMES)


def probe_asset(client: TractianClient, asset_id: str) -> AssetProbe:
    """Sonda o ativo nos dois regimes: cadastro fixo e evidência real da rodada."""

    catalog = client.get_asset(asset_id, seed=CATALOG_SEED)
    catalog_data = catalog.data if isinstance(catalog.data, dict) else {}
    asset = client.get_asset(asset_id)
    data = asset.data if isinstance(asset.data, dict) else {}
    statuses: dict[str, str | None] = {
        "asset": asset.evidence_status.value if asset.evidence_status else None,
        "analyses": _status(client.list_asset_analyses(asset_id)),
        "baseline": _status(client.get_baseline(asset_id)),
        "rms": _status(client.get_rms(asset_id)),
        "spectrum": _status(client.get_spectrum(asset_id)),
        "data_quality": _status(client.get_data_quality(asset_id)),
    }
    return AssetProbe(
        asset_id=asset_id,
        exists=catalog.transport_ok,
        catalog_name=catalog_data.get("name") if isinstance(catalog_data.get("name"), str) else None,
        catalog_machine_type=(
            catalog_data.get("machine_type") if isinstance(catalog_data.get("machine_type"), str) else None
        ),
        evidence_status_by_category={key: statuses[key] for key in _ASSET_CATEGORIES},
        grounded_fields_present=GROUNDED_ASSET_FIELDS <= set(data),
    )


def _status(result: ClientResult) -> str | None:
    return result.evidence_status.value if result.evidence_status else None


def build_catalog(client: TractianClient, asset_ids: tuple[str, ...]) -> tuple[dict[str, str], str]:
    """Léxico substantivo→família a partir do catálogo alcançável pela API.

    O catálogo é expandido para as empresas dos ativos citados; nenhum termo é
    inventado, então um substantivo fora dele permanece ``UNVERIFIABLE`` em vez
    de virar contradição presumida.
    """

    names: dict[str, str] = {}
    companies: set[str] = set()
    for asset_id in asset_ids:
        result = client.get_asset(asset_id, seed=CATALOG_SEED)
        data = result.data if isinstance(result.data, dict) else {}
        if isinstance(data.get("company_id"), str):
            companies.add(data["company_id"])
    for company_id in sorted(companies):
        listing = client.list_company_assets(company_id, seed=CATALOG_SEED)
        payload = listing.data if isinstance(listing.data, dict) else {}
        for item in payload.get("assets", []) or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("machine_type"), str):
                names[item["name"]] = item["machine_type"]

    lexicon: dict[str, set[str]] = {}
    for name, machine_type in names.items():
        tokens = fold(name).split()
        if not tokens:
            continue
        lexicon.setdefault(tokens[0], set()).add(machine_family(machine_type) or machine_type)
    resolved = {head: next(iter(families)) for head, families in sorted(lexicon.items()) if len(families) == 1}
    return resolved, f"api_company_listing:{','.join(sorted(companies)) or 'none'}"


def descriptor_tokens(message: str, position: int) -> tuple[str, ...]:
    """Janela curta antes do identificador, sem preposições.

    Os templates DEV escrevem o tipo de máquina como "<substantivo> de
    <qualificador> asset_X". Olhar só o token imediatamente anterior captura o
    qualificador ("acabamento") e perde o substantivo ("spindle"), por isso a
    janela tem largura fixa e as stopwords são descartadas.
    """

    window = fold(message[:position]).split()[-DESCRIPTOR_WINDOW:]
    return tuple(token for token in window if token and token not in DESCRIPTOR_STOPWORDS)


def audit_case(
    sample: UnderstandingSample,
    probes: dict[str, AssetProbe],
    lexicon: dict[str, str],
    *,
    temporal_supported: bool,
) -> CaseCoverage:
    message = sample.input.message
    context_refs = tuple(sample.input.available_context.asset_refs)
    mentions: list[AssetMention] = []
    seen: set[str] = set()

    for match in ASSET_ID_PATTERN.finditer(message):
        asset_id = match.group(0)
        seen.add(asset_id)
        probe = probes.get(asset_id)
        tokens = descriptor_tokens(message, match.start())
        resolved = next(((token, lexicon[token]) for token in tokens if token in lexicon), None)
        descriptor = " ".join(tokens) or None
        descriptor_family = resolved[1] if resolved else None
        api_family = probe.family if probe else None
        if not tokens:
            alignment = DescriptorAlignment.NO_DESCRIPTOR
        elif descriptor_family is None or api_family is None:
            alignment = DescriptorAlignment.UNVERIFIABLE
        elif descriptor_family == api_family:
            alignment = DescriptorAlignment.CORROBORATED
        else:
            alignment = DescriptorAlignment.CONTRADICTED
        mentions.append(
            AssetMention(
                asset_id=asset_id,
                exists_in_api=bool(probe and probe.exists),
                descriptor=descriptor,
                descriptor_alignment=alignment,
                descriptor_family=descriptor_family,
                api_family=api_family,
            )
        )

    for asset_id in context_refs:
        if asset_id in seen:
            continue
        probe = probes.get(asset_id)
        mentions.append(
            AssetMention(
                asset_id=asset_id,
                exists_in_api=bool(probe and probe.exists),
                descriptor=None,
                descriptor_alignment=DescriptorAlignment.NO_DESCRIPTOR,
                api_family=probe.family if probe else None,
            )
        )

    referenced = tuple(dict.fromkeys(mention.asset_id for mention in mentions))
    resolvable = [mention for mention in mentions if mention.exists_in_api]
    grounded_reachable = any(
        (probes[mention.asset_id].evidence_status_by_category.get("asset") in {"complete", "partial"})
        and probes[mention.asset_id].grounded_fields_present
        for mention in resolvable
        if mention.asset_id in probes
    )

    if not resolvable:
        alignment = CoverageAlignment.IMPOSSIBLE_FROM_API
    elif any(mention.descriptor_alignment is DescriptorAlignment.CONTRADICTED for mention in mentions):
        alignment = CoverageAlignment.MISALIGNED
    elif any(mention.descriptor_alignment is DescriptorAlignment.UNVERIFIABLE for mention in mentions) or not grounded_reachable:
        alignment = CoverageAlignment.PARTIALLY_ALIGNED
    else:
        alignment = CoverageAlignment.FULLY_ALIGNED

    folded_message = fold(message)
    temporal_requested = any(marker in folded_message for marker in TEMPORAL_MARKERS)

    warnings: list[str] = []
    if alignment is not CoverageAlignment.FULLY_ALIGNED:
        warnings.append("DATA_COVERAGE_WARNING")
    if alignment is CoverageAlignment.MISALIGNED:
        warnings.append("DESCRIPTOR_CONTRADICTS_API_RECORD")
    if alignment is CoverageAlignment.IMPOSSIBLE_FROM_API:
        warnings.append("NO_RESOLVABLE_ENTITY")
    if temporal_requested and not temporal_supported:
        warnings.append("TEMPORAL_CONTEXT_NOT_REPRESENTED_IN_API")
    if not grounded_reachable and resolvable:
        warnings.append("GROUNDED_ANSWER_NOT_REACHABLE_FROM_ASSET_RECORD")

    return CaseCoverage(
        sample_id=sample.sample_id,
        referenced_asset_ids=referenced,
        mentions=tuple(mentions),
        alignment=alignment,
        temporal_context_requested=temporal_requested,
        temporal_context_available=temporal_supported,
        grounded_answer_reachable=grounded_reachable,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def audit_coverage(samples: tuple[UnderstandingSample, ...], client: TractianClient) -> DataCoverageReport:
    """Ponto único de entrada: sonda a API e classifica todos os casos DEV."""

    referenced = tuple(
        dict.fromkeys(
            [asset_id for sample in samples for asset_id in ASSET_ID_PATTERN.findall(sample.input.message)]
            + [asset_id for sample in samples for asset_id in sample.input.available_context.asset_refs]
        )
    )
    lexicon, catalog_source = build_catalog(client, referenced)
    probes = {asset_id: probe_asset(client, asset_id) for asset_id in referenced}
    temporal_supported = temporal_filtering_supported()
    cases = tuple(audit_case(sample, probes, lexicon, temporal_supported=temporal_supported) for sample in samples)

    unverifiable = Counter(
        mention.descriptor
        for case in cases
        for mention in case.mentions
        if mention.descriptor_alignment is DescriptorAlignment.UNVERIFIABLE and mention.descriptor
    )
    counts = Counter(case.alignment for case in cases)
    return DataCoverageReport(
        catalog_source=catalog_source,
        catalog_size=len(lexicon),
        probes=tuple(probes.values()),
        descriptor_lexicon=lexicon,
        unverifiable_descriptor_terms=dict(unverifiable),
        cases=cases,
        cases_fully_aligned=counts[CoverageAlignment.FULLY_ALIGNED],
        cases_partially_aligned=counts[CoverageAlignment.PARTIALLY_ALIGNED],
        cases_misaligned=counts[CoverageAlignment.MISALIGNED],
        cases_impossible_from_api=counts[CoverageAlignment.IMPOSSIBLE_FROM_API],
        cases_grounded_answer_reachable=sum(case.grounded_answer_reachable for case in cases),
        cases_requesting_unavailable_temporal_context=sum(
            case.temporal_context_requested and not case.temporal_context_available for case in cases
        ),
        temporal_filtering_supported_by_tools=temporal_supported,
    )

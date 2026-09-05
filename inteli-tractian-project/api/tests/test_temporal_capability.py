"""Gap temporal da Etapa 09.6: a ausência é informada, nunca fabricada."""

import pytest

from app.evaluation.tool_capabilities import TemporalSupport, build_matrix
from app.intelligence import CapabilityContract, InvestigatorInput
from app.investigation.temporal_policy import (
    TEMPORAL_PARAMETER_NAMES,
    TemporalHandling,
    TemporalReasonCode,
    assess_temporal_request,
    detect_temporal_request,
    is_temporal_argument,
)
from app.llm.contracts import LLMMetadata, LLMResponse, LLMResponseStatus
from app.llm.investigator import InvestigatorValidationCategory, validate_investigation_decision
from app.tools import get_investigator_tools


# --------------------------------------------------------------------------- #
# Matriz de capacidade
# --------------------------------------------------------------------------- #


def test_no_read_tool_accepts_a_temporal_filter_today() -> None:
    matrix = build_matrix()

    assert matrix.any_tool_supports_temporal_filter is False
    assert matrix.filterable_tools == ()
    assert len(matrix.tools) == len(get_investigator_tools())


def test_matrix_separates_filtering_from_timestamped_payloads() -> None:
    matrix = build_matrix()

    timestamped = set(matrix.tools_returning_timestamped_data)
    assert "get_asset_rms" in timestamped
    assert "list_asset_analyses" in timestamped
    # Cadastro não é datado: não pode ser confundido com série temporal.
    assert matrix.by_name("get_asset_context").temporal_support is TemporalSupport.NONE


def test_no_tool_schema_gained_an_invented_temporal_parameter() -> None:
    """O schema não ganha campo só para o modelo passar (Etapa 09.6, §6)."""

    for tool in get_investigator_tools():
        assert not set(tool.input_schema.model_fields) & TEMPORAL_PARAMETER_NAMES


# --------------------------------------------------------------------------- #
# Política temporal
# --------------------------------------------------------------------------- #


def test_request_without_temporal_marker_proceeds_normally() -> None:
    assessment = assess_temporal_request("Qual o tipo do asset_S425?")

    assert assessment.temporal_request_detected is False
    assert assessment.reason_code is TemporalReasonCode.NO_TEMPORAL_REQUEST
    assert assessment.handling is TemporalHandling.PROCEED_WITHOUT_FILTER


def test_temporal_request_with_timestamped_data_proceeds_and_declares_the_limit() -> None:
    """Caso A: pedido temporal e tool sem filtro — não criar time_window."""

    assessment = assess_temporal_request(
        "A vibração mudou desde o último turno no asset_S425?",
        timestamped_tools=("get_asset_rms",),
    )

    assert assessment.temporal_request_detected is True
    assert assessment.reason_code is TemporalReasonCode.TEMPORAL_FILTER_UNSUPPORTED
    assert assessment.handling is TemporalHandling.PROCEED_WITHOUT_FILTER
    assert "não invente" in assessment.guidance.lower()


def test_temporal_request_without_any_path_asks_or_escalates() -> None:
    """Caso B: pedido temporal e nenhum caminho possível."""

    relative = assess_temporal_request("O que houve desde o último turno?")
    assert relative.reason_code is TemporalReasonCode.TEMPORAL_CONTEXT_REQUIRED
    assert relative.handling is TemporalHandling.ASK_USER

    absolute = assess_temporal_request("Compare com a parada programada.")
    assert absolute.reason_code is TemporalReasonCode.TEMPORAL_DATA_UNAVAILABLE
    assert absolute.handling is TemporalHandling.ESCALATE


def test_a_tool_that_really_filtered_would_be_allowed_to() -> None:
    """Caso C: se existisse suporte real, a política permitiria usá-lo."""

    assessment = assess_temporal_request(
        "Últimas 8 horas do asset_S425", filterable_tools=("get_asset_rms",)
    )

    assert assessment.handling is TemporalHandling.PROCEED_WITHOUT_FILTER
    assert assessment.reason_code is TemporalReasonCode.NO_TEMPORAL_REQUEST


@pytest.mark.parametrize("marker", ["turno", "últimas seis horas", "desde a troca de carga", "nesta semana"])
def test_dev_temporal_markers_are_recognised(marker: str) -> None:
    assert detect_temporal_request(f"Verifique o ativo {marker}.") is True


@pytest.mark.parametrize(
    "field, temporal",
    [
        ("time_window", True),
        ("hours", True),
        ("window", True),
        ("tool_request.arguments.since", True),
        ("asset_id", False),
        ("point_id", False),
        (None, False),
    ],
)
def test_temporal_arguments_are_recognised_anywhere_in_the_path(field, temporal) -> None:
    assert is_temporal_argument(field) is temporal


# --------------------------------------------------------------------------- #
# Validação da decisão
# --------------------------------------------------------------------------- #


def _decision_response(arguments: dict) -> LLMResponse:
    payload = {
        "decision_id": "dec_temporal",
        "type": "tool_call",
        "reason_codes": ["TEST"],
        "tool_request": {"tool_name": "get_asset_rms", "arguments": arguments},
    }
    return LLMResponse(
        request_id="req",
        provider="gemini",
        model="modelo",
        status=LLMResponseStatus.SUCCESS,
        output=payload,
        duration_ms=1.0,
        metadata=LLMMetadata(prompt_version="e2e_investigator_v4"),
    )


def test_invented_temporal_argument_gets_its_own_category() -> None:
    """Caso D: `hours` inventado é rejeitado com categoria específica."""

    result, decision, _ = validate_investigation_decision(
        _decision_response({"asset_id": "asset_S425", "hours": 8})
    )

    assert decision is None
    assert result.category is InvestigatorValidationCategory.UNSUPPORTED_TEMPORAL_ARGUMENT
    assert result.field is not None and "hours" in result.field
    assert "temporal" in result.message_sanitized.lower()


def test_non_temporal_invalid_argument_keeps_the_generic_category() -> None:
    result, decision, _ = validate_investigation_decision(
        _decision_response({"asset_id": "asset_S425", "campo_inexistente": 1})
    )

    assert decision is None
    assert result.category is InvestigatorValidationCategory.INVALID_TOOL_ARGUMENTS


def test_valid_arguments_still_pass() -> None:
    result, decision, _ = validate_investigation_decision(
        _decision_response({"asset_id": "asset_S425", "point_id": "pt_S425_de"})
    )

    assert result.valid and decision is not None


# --------------------------------------------------------------------------- #
# Contrato entregue ao Investigator
# --------------------------------------------------------------------------- #


def test_investigator_receives_the_real_argument_contract() -> None:
    from scripts.run_full_dev_evaluation import capability_contracts

    contracts = {item.name: item for item in capability_contracts()}

    assert set(contracts) == {tool.name for tool in get_investigator_tools()}
    rms = contracts["get_asset_rms"]
    assert set(rms.accepted_arguments) == {"asset_id", "point_id"}
    assert rms.required_arguments == ("asset_id",)
    assert not set(rms.accepted_arguments) & TEMPORAL_PARAMETER_NAMES
    assert rms.argument_schema.get("properties")


def test_capability_contract_rejects_a_tool_outside_the_allowlist() -> None:
    with pytest.raises(ValueError, match="READ tool autorizada"):
        CapabilityContract(name="update_asset_config", accepted_arguments=("asset_id",))


def test_investigator_input_carries_contracts_and_guidance() -> None:
    fields = InvestigatorInput.model_fields

    assert "capability_contracts" in fields
    assert "temporal_guidance" in fields

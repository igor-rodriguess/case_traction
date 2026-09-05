"""Fixtures do contract smoke: nenhum provider real é chamado."""

from scripts.smoke_llm_contracts import (
    case_definitions,
    fixture_conclusion,
    fixture_inputs,
    fixture_understanding_input,
    validation_error_summary,
)


def test_contract_smoke_fixtures_are_synthetic_and_strict() -> None:
    planner, investigator, reporter = fixture_inputs()
    assert planner.permitted_context["source"] == "synthetic_contract_smoke"
    assert investigator.permitted_capabilities[0].name == "get_asset_rms"
    assert reporter.conclusion == fixture_conclusion()
    assert fixture_understanding_input().available_context.asset_refs == ("asset_B211",)


def test_contract_smoke_requests_target_the_canonical_schemas() -> None:
    cases = case_definitions()
    assert [component for component, *_ in cases] == ["understanding", "planner", "investigator", "reporter"]
    for _, _, request, _ in cases:
        assert request.expected_schema
        expected_version = {
            "understanding": "understanding_prompt_v2",
            "investigator": "contract_smoke.v5.investigator",
        }.get(request.agent_role, f"contract_smoke.v4.{request.agent_role}")
        assert request.prompt_version == expected_version
        assert request.messages


def test_contract_smoke_diagnostic_accepts_missing_provider_output() -> None:
    assert validation_error_summary("investigator", None) is None

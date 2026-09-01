"""Wrappers ACTION catalogados, mas não autorizados ao Investigator."""

from __future__ import annotations

from app.integrations.tractian_client import ClientResult, TractianClient
from app.tools.schemas import (
    AnalysisActionInput,
    AssetConfigUpdateInput,
    CaseEscalationInput,
    ModelRetrainingInput,
)


def request_asset_config_update(
    client: TractianClient,
    args: AssetConfigUpdateInput,
) -> ClientResult:
    return client.update_asset_config(
        args.asset_id,
        changes=args.changes.model_dump(mode="json"),
        justification=args.justification,
    )


def request_analysis_reprocessing(
    client: TractianClient,
    args: AnalysisActionInput,
) -> ClientResult:
    return client.reprocess_analysis(
        args.analysis_id,
        justification=args.justification,
        params=args.params,
    )


def request_specialist_analysis(
    client: TractianClient,
    args: AnalysisActionInput,
) -> ClientResult:
    return client.request_specialist_analysis(
        args.analysis_id,
        justification=args.justification,
        params=args.params,
    )


def request_model_retraining(
    client: TractianClient,
    args: ModelRetrainingInput,
) -> ClientResult:
    return client.request_model_retraining(
        args.model_id,
        justification=args.justification,
        params=args.params,
    )


def request_case_escalation(
    client: TractianClient,
    args: CaseEscalationInput,
) -> ClientResult:
    return client.escalate_case(
        args.case_id,
        justification=args.justification,
        params=args.params,
    )

"""Wrappers READ aprovados para a superfície investigativa."""

from __future__ import annotations

from app.integrations.tractian_client import ClientResult, TractianClient
from app.tools.schemas import (
    AnalysisIdInput,
    AssetIdInput,
    AssetPointInput,
    KnowledgeDocumentInput,
    KnowledgeSearchInput,
    ListAssetAnalysesInput,
    ModelIdInput,
)


def get_asset_context(client: TractianClient, args: AssetIdInput) -> ClientResult:
    return client.get_asset(args.asset_id)


def list_asset_analyses(client: TractianClient, args: ListAssetAnalysesInput) -> ClientResult:
    status = args.status.value if args.status is not None else None
    return client.list_asset_analyses(args.asset_id, status=status)


def get_analysis_details(client: TractianClient, args: AnalysisIdInput) -> ClientResult:
    return client.get_analysis(args.analysis_id)


def get_asset_baseline(client: TractianClient, args: AssetPointInput) -> ClientResult:
    return client.get_baseline(args.asset_id, point_id=args.point_id)


def get_asset_rms(client: TractianClient, args: AssetPointInput) -> ClientResult:
    return client.get_rms(args.asset_id, point_id=args.point_id)


def get_asset_spectrum(client: TractianClient, args: AssetPointInput) -> ClientResult:
    return client.get_spectrum(args.asset_id, point_id=args.point_id)


def get_asset_data_quality(client: TractianClient, args: AssetPointInput) -> ClientResult:
    return client.get_data_quality(args.asset_id, point_id=args.point_id)


def get_model_capabilities(client: TractianClient, args: ModelIdInput) -> ClientResult:
    return client.get_model(args.model_id)


def search_industrial_knowledge(client: TractianClient, args: KnowledgeSearchInput) -> ClientResult:
    knowledge_type = args.knowledge_type.value if args.knowledge_type is not None else None
    return client.search_knowledge(args.query, knowledge_type=knowledge_type)


def get_knowledge_document(client: TractianClient, args: KnowledgeDocumentInput) -> ClientResult:
    return client.get_knowledge_document(args.doc_id)

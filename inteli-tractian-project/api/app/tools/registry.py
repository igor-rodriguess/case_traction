"""Registry explícito da superfície aprovada na Etapa 03A."""

from __future__ import annotations

from app.integrations.tractian_client import OperationKind
from app.tools import action_tools, read_tools
from app.tools.base import ExecutionPolicy, ToolDefinition, ToolExposure
from app.tools.schemas import (
    AnalysisActionInput,
    AnalysisIdInput,
    AssetConfigUpdateInput,
    AssetIdInput,
    AssetPointInput,
    CaseEscalationInput,
    KnowledgeDocumentInput,
    KnowledgeSearchInput,
    ListAssetAnalysesInput,
    ModelIdInput,
    ModelRetrainingInput,
)


INVESTIGATOR_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="get_asset_context",
        category="asset",
        operation_kind=OperationKind.READ,
        description="Consulta identidade, hierarquia e configuração do ativo; não retorna séries técnicas.",
        input_schema=AssetIdInput,
        client_operation="get_asset",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_asset_context,
    ),
    ToolDefinition(
        name="list_asset_analyses",
        category="analysis",
        operation_kind=OperationKind.READ,
        description="Lista análises de um ativo para descobrir candidatos; use o detalhe para examinar uma análise.",
        input_schema=ListAssetAnalysesInput,
        client_operation="list_asset_analyses",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.list_asset_analyses,
    ),
    ToolDefinition(
        name="get_analysis_details",
        category="analysis",
        operation_kind=OperationKind.READ,
        description="Consulta achados e evidências de uma análise já identificada; não lista análises do ativo.",
        input_schema=AnalysisIdInput,
        client_operation="get_analysis",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_analysis_details,
    ),
    ToolDefinition(
        name="get_asset_baseline",
        category="technical_data",
        operation_kind=OperationKind.READ,
        description="Consulta a referência histórica do ativo; não mede a qualidade dos dados atuais.",
        input_schema=AssetPointInput,
        client_operation="get_baseline",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_asset_baseline,
    ),
    ToolDefinition(
        name="get_asset_rms",
        category="technical_data",
        operation_kind=OperationKind.READ,
        description="Consulta a evolução agregada da vibração RMS; não identifica componentes de frequência.",
        input_schema=AssetPointInput,
        client_operation="get_rms",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_asset_rms,
    ),
    ToolDefinition(
        name="get_asset_spectrum",
        category="technical_data",
        operation_kind=OperationKind.READ,
        description="Consulta picos e bandas do espectro para análise em frequência; difere da tendência RMS agregada.",
        input_schema=AssetPointInput,
        client_operation="get_spectrum",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_asset_spectrum,
    ),
    ToolDefinition(
        name="get_asset_data_quality",
        category="technical_data",
        operation_kind=OperationKind.READ,
        description="Consulta completude, frescor e qualidade da evidência; não representa a condição do ativo.",
        input_schema=AssetPointInput,
        client_operation="get_data_quality",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_asset_data_quality,
    ),
    ToolDefinition(
        name="get_model_capabilities",
        category="model",
        operation_kind=OperationKind.READ,
        description="Consulta cobertura, requisitos e estado do modelo; não solicita retreinamento.",
        input_schema=ModelIdInput,
        client_operation="get_model",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_model_capabilities,
    ),
    ToolDefinition(
        name="search_industrial_knowledge",
        category="knowledge",
        operation_kind=OperationKind.READ,
        description="Busca referências industriais por termos; use recuperação por ID quando o documento já for conhecido.",
        input_schema=KnowledgeSearchInput,
        client_operation="search_knowledge",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.search_industrial_knowledge,
    ),
    ToolDefinition(
        name="get_knowledge_document",
        category="knowledge",
        operation_kind=OperationKind.READ,
        description="Recupera um documento específico por ID; não realiza busca exploratória.",
        input_schema=KnowledgeDocumentInput,
        client_operation="get_knowledge_document",
        exposure=ToolExposure.INVESTIGATOR,
        execution_policy=ExecutionPolicy.UNRESTRICTED,
        handler=read_tools.get_knowledge_document,
    ),
)


ACTION_TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="request_asset_config_update",
        category="action",
        operation_kind=OperationKind.ACTION,
        description="Solicita alteração tipada da configuração de um ativo; aceite não comprova persistência.",
        input_schema=AssetConfigUpdateInput,
        client_operation="update_asset_config",
        exposure=ToolExposure.CATALOG_ONLY,
        execution_policy=ExecutionPolicy.FUTURE_POLICY_REQUIRED,
        handler=action_tools.request_asset_config_update,
    ),
    ToolDefinition(
        name="request_analysis_reprocessing",
        category="action",
        operation_kind=OperationKind.ACTION,
        description="Solicita novo processamento de uma análise; aceite não representa conclusão do processamento.",
        input_schema=AnalysisActionInput,
        client_operation="reprocess_analysis",
        exposure=ToolExposure.CATALOG_ONLY,
        execution_policy=ExecutionPolicy.FUTURE_POLICY_REQUIRED,
        handler=action_tools.request_analysis_reprocessing,
    ),
    ToolDefinition(
        name="request_specialist_analysis",
        category="action",
        operation_kind=OperationKind.ACTION,
        description="Solicita análise especializada; aceite não comprova atendimento ou handoff concluído.",
        input_schema=AnalysisActionInput,
        client_operation="request_specialist_analysis",
        exposure=ToolExposure.CATALOG_ONLY,
        execution_policy=ExecutionPolicy.FUTURE_POLICY_REQUIRED,
        handler=action_tools.request_specialist_analysis,
    ),
    ToolDefinition(
        name="request_model_retraining",
        category="action",
        operation_kind=OperationKind.ACTION,
        description="Solicita retreinamento de modelo; aceite não comprova criação ou conclusão de um job.",
        input_schema=ModelRetrainingInput,
        client_operation="request_model_retraining",
        exposure=ToolExposure.CATALOG_ONLY,
        execution_policy=ExecutionPolicy.FUTURE_POLICY_REQUIRED,
        handler=action_tools.request_model_retraining,
    ),
    ToolDefinition(
        name="request_case_escalation",
        category="action",
        operation_kind=OperationKind.ACTION,
        description="Solicita escalonamento humano de um caso; aceite não comprova atendimento posterior.",
        input_schema=CaseEscalationInput,
        client_operation="escalate_case",
        exposure=ToolExposure.CATALOG_ONLY,
        execution_policy=ExecutionPolicy.FUTURE_POLICY_REQUIRED,
        handler=action_tools.request_case_escalation,
    ),
)


def get_investigator_tools() -> tuple[ToolDefinition, ...]:
    """Retorna exclusivamente as dez READ tools autorizadas ao Investigator."""

    return INVESTIGATOR_TOOLS


def get_action_tools() -> tuple[ToolDefinition, ...]:
    """Retorna ACTION capabilities para inspeção, não autorização autônoma."""

    return ACTION_TOOLS


def inspect_tool_surface() -> list[dict[str, object]]:
    """Gera saída determinística para revisão humana, sem utilizar LLM."""

    return [tool.inspection() for tool in (*INVESTIGATOR_TOOLS, *ACTION_TOOLS)]

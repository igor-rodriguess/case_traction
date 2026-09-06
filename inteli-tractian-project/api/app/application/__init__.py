"""Camada de aplicação: coordena o ciclo de vida da investigação.

O grafo decide. O Eval julga. A política final resolve. Esta camada organiza a
ordem e garante que cada etapa chegue ao banco quando passa a ser verdade.
"""

from app.application.investigation_service import (
    CreatedInvestigation,
    InvestigationService,
    NewInvestigation,
)
from app.application.pipeline import PipelineConfig, PipelineResult, run_pipeline

__all__ = [
    "CreatedInvestigation",
    "InvestigationService",
    "NewInvestigation",
    "PipelineConfig",
    "PipelineResult",
    "run_pipeline",
]

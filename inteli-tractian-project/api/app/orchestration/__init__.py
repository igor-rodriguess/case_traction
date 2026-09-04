"""Orquestração determinística da investigação.

LangGraph organiza transições. Ele não toma decisões de investigação.
"""

from app.orchestration.investigation_graph import (
    InvestigationGraphDependencies,
    build_investigation_graph,
)

__all__ = ["InvestigationGraphDependencies", "build_investigation_graph"]

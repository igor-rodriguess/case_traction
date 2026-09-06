"""Persistência da investigação no Supabase.

Fronteira única entre o domínio e o banco. Nada fora deste pacote abre conexão,
e nenhuma credencial atravessa a fronteira em direção à API ou ao frontend.
"""

from .progressive import ProgressiveWriter, RunIdentity
from .repository import InvestigationRepository, PersistedRun, PersistenceError
from .settings import DatabaseSettings, MissingConfiguration, database_settings, is_configured

__all__ = [
    "DatabaseSettings",
    "InvestigationRepository",
    "MissingConfiguration",
    "PersistedRun",
    "PersistenceError",
    "ProgressiveWriter",
    "RunIdentity",
    "database_settings",
    "is_configured",
]

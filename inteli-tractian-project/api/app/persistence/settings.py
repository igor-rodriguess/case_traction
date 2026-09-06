"""Configuração de acesso ao banco.

Lê do ambiente e nada mais. Nenhum valor default de credencial, nenhum segredo
em código, nenhum caminho alternativo que aceite chave por argumento.

A separação de papéis é explícita:

* `SUPABASE_DB_URL` e `SUPABASE_SECRET_KEY` são credenciais de **backend**. Não
  saem daqui e nunca aparecem numa resposta de API.
* `SUPABASE_PUBLISHABLE_KEY` é a única que poderia ir ao cliente, e este produto
  não precisa dela: o frontend fala com a API, não com o banco.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _API_ROOT / ".env"


class MissingConfiguration(RuntimeError):
    """Alguma variável obrigatória não está definida.

    A mensagem nomeia a variável que falta e nunca cita o valor de nenhuma outra.
    """


def _load_env_file() -> None:
    """Carrega `api/.env` quando o processo não recebeu o ambiente pronto."""
    if not _ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ENV_FILE, override=False)


@dataclass(frozen=True)
class DatabaseSettings:
    """Parâmetros de conexão. `url` carrega a senha e por isso nunca é logada."""

    url: str
    connect_timeout: int = 30
    application_name: str = "tractian-investigation-api"

    def __repr__(self) -> str:  # pragma: no cover - proteção contra log acidental
        return f"DatabaseSettings(url=<oculto>, timeout={self.connect_timeout}s)"

    __str__ = __repr__


def database_settings() -> DatabaseSettings:
    _load_env_file()
    url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not url:
        raise MissingConfiguration(
            "Configuração ausente: SUPABASE_DB_URL. "
            "Defina-a no ambiente da API; nenhuma outra credencial precisa ser informada."
        )
    return DatabaseSettings(url=url)


def is_configured() -> bool:
    """Permite que a API suba sem banco, para desenvolvimento e testes."""
    _load_env_file()
    return bool(os.environ.get("SUPABASE_DB_URL", "").strip())

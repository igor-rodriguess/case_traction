# -*- coding: utf-8 -*-
"""Aplica as migrations versionadas de `supabase/migrations` no banco conectado.

Usa a mesma tabela de controle do Supabase CLI
(`supabase_migrations.schema_migrations`), então o histórico continua legível
por qualquer ferramenta oficial.

Regras:

* cada migration roda dentro de uma transação — ou aplica inteira, ou nada;
* uma migration já registrada é ignorada;
* nenhuma credencial é impressa, nem em erro.

Uso:
    python api/scripts/apply_migrations.py            # aplica pendentes
    python api/scripts/apply_migrations.py --status   # só lista
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - dependência de ambiente
    sys.exit("psycopg não está instalado no ambiente da API.")

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
ENV_FILE = REPO_ROOT / "api" / ".env"

CONTROL_SCHEMA = "supabase_migrations"
CONTROL_TABLE = "schema_migrations"


def database_url() -> str:
    """Lê a URL do ambiente. O valor nunca é exibido."""
    if load_dotenv is not None and ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit(
            "Configuração ausente: SUPABASE_DB_URL.\n"
            "Defina-a em api/.env — nenhum outro valor precisa ser informado."
        )
    return url


def discovered() -> list[tuple[str, str, Path]]:
    """(version, name, path) para cada arquivo `<version>_<name>.sql`."""
    if not MIGRATIONS_DIR.is_dir():
        sys.exit(f"Diretório de migrations não encontrado: {MIGRATIONS_DIR}")
    found = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        stem = path.stem
        version, _, name = stem.partition("_")
        if not version.isdigit():
            sys.exit(f"Nome de migration inválido (esperado <timestamp>_<nome>.sql): {path.name}")
        found.append((version, name or stem, path))
    return found


def ensure_control_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(f"create schema if not exists {CONTROL_SCHEMA}")
        cur.execute(
            f"""
            create table if not exists {CONTROL_SCHEMA}.{CONTROL_TABLE} (
                version    text primary key,
                name       text,
                statements text[]
            )
            """
        )
    conn.commit()


def applied_versions(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(f"select version from {CONTROL_SCHEMA}.{CONTROL_TABLE}")
        return {row[0] for row in cur.fetchall()}


def apply(conn: psycopg.Connection, version: str, name: str, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            f"insert into {CONTROL_SCHEMA}.{CONTROL_TABLE} (version, name, statements) "
            "values (%s, %s, %s)",
            (version, name, [sql]),
        )
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aplica migrations no Supabase conectado.")
    parser.add_argument("--status", action="store_true", help="apenas lista o que está pendente")
    args = parser.parse_args(argv)

    migrations = discovered()
    if not migrations:
        print("Nenhuma migration encontrada.")
        return 0

    with psycopg.connect(database_url(), connect_timeout=30) as conn:
        ensure_control_table(conn)
        already = applied_versions(conn)

        pending = [m for m in migrations if m[0] not in already]

        print(f"Migrations no repositório: {len(migrations)}")
        for version, name, _ in migrations:
            mark = "aplicada" if version in already else "pendente"
            print(f"  [{mark:8s}] {version}  {name}")

        if args.status:
            return 0
        if not pending:
            print("\nNada a aplicar.")
            return 0

        print()
        for version, name, path in pending:
            print(f"Aplicando {version} {name} ...", end=" ", flush=True)
            try:
                apply(conn, version, name, path)
            except psycopg.Error as exc:
                conn.rollback()
                # Mensagem do Postgres, sem a URL de conexão.
                print("FALHOU")
                print(f"  {exc.__class__.__name__}: {str(exc).strip()}")
                return 1
            print("ok")

    print("\nMigrations aplicadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

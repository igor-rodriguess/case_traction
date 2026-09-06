# -*- coding: utf-8 -*-
"""Confere o schema real depois da migration.

Uma migration que retorna zero não prova nada: o que prova é o banco
respondendo. Este script lê o catálogo do Postgres e falha se qualquer
garantia estrutural estiver faltando.

Nenhuma credencial é impressa.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "investigation"

EXPECTED_TABLES = [
    "arbitration",
    "claim",
    "claim_evidence",
    "conclusion",
    "evaluation",
    "evaluation_critical_score",
    "evaluation_finding",
    "evidence_record",
    "human_handoff",
    "investigation_run",
    "judge_agreement",
    "judge_criterion_score",
    "judge_disagreement",
    "judge_result",
    "technical_report",
    "trace_event",
]

# Garantias que dão ao banco o mesmo poder de recusa que os contratos Pydantic.
REQUIRED_CONSTRAINTS = [
    ("evidence_record", "evidence_record_lineage_fkey"),
    ("evaluation", "evaluation_hard_failure_blocks_approval"),
    ("evaluation", "evaluation_verdict_matches_approval"),
    ("judge_disagreement", "judge_disagreement_delta_matches_scores"),
    ("judge_criterion_score", "judge_criterion_low_score_needs_reference"),
    ("investigation_run", "investigation_run_case_id_key"),
    ("trace_event", "trace_event_run_sequence_key"),
    ("evidence_record", "evidence_record_run_evidence_key"),
]


def url() -> str:
    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / "api" / ".env")
    value = os.environ.get("SUPABASE_DB_URL")
    if not value:
        sys.exit("Configuração ausente: SUPABASE_DB_URL")
    return value


def main() -> int:
    failures: list[str] = []

    with psycopg.connect(url(), connect_timeout=30) as conn, conn.cursor() as cur:
        # --- tabelas ---------------------------------------------------------
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = %s order by 1",
            (SCHEMA,),
        )
        tables = [r[0] for r in cur.fetchall()]
        print(f"TABELAS ({len(tables)}):")
        for name in tables:
            print(f"  {SCHEMA}.{name}")
        missing = set(EXPECTED_TABLES) - set(tables)
        if missing:
            failures.append(f"tabelas ausentes: {sorted(missing)}")

        # --- chaves primárias ------------------------------------------------
        cur.execute(
            """
            select c.relname, con.conname
            from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = %s and con.contype = 'p'
            order by 1
            """,
            (SCHEMA,),
        )
        pks = cur.fetchall()
        print(f"\nCHAVES PRIMÁRIAS: {len(pks)}")
        without_pk = set(tables) - {t for t, _ in pks}
        if without_pk:
            failures.append(f"tabelas sem PK: {sorted(without_pk)}")

        # --- chaves estrangeiras --------------------------------------------
        cur.execute(
            """
            select c.relname, con.conname, rc.relname
            from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_class rc on rc.oid = con.confrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = %s and con.contype = 'f'
            order by 1, 2
            """,
            (SCHEMA,),
        )
        fks = cur.fetchall()
        print(f"CHAVES ESTRANGEIRAS: {len(fks)}")
        for table, name, target in fks:
            print(f"  {table} -> {target}  ({name})")

        # --- unique ----------------------------------------------------------
        cur.execute(
            """
            select c.relname, con.conname
            from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = %s and con.contype = 'u'
            order by 1, 2
            """,
            (SCHEMA,),
        )
        uniques = cur.fetchall()
        print(f"\nUNIQUE: {len(uniques)}")
        for table, name in uniques:
            print(f"  {table}: {name}")

        # --- check -----------------------------------------------------------
        cur.execute(
            """
            select c.relname, con.conname
            from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = %s and con.contype = 'c'
            """,
            (SCHEMA,),
        )
        checks = cur.fetchall()
        print(f"\nCHECK: {len(checks)}")

        present = {(t, n) for t, n in checks + uniques + fks_names(fks)}
        for table, name in REQUIRED_CONSTRAINTS:
            if (table, name) not in present:
                failures.append(f"constraint obrigatória ausente: {table}.{name}")
            else:
                print(f"  garantia presente: {table}.{name}")

        # --- índices ---------------------------------------------------------
        cur.execute(
            "select tablename, indexname from pg_indexes where schemaname = %s order by 1, 2",
            (SCHEMA,),
        )
        indexes = cur.fetchall()
        print(f"\nÍNDICES: {len(indexes)}")

        # --- RLS -------------------------------------------------------------
        cur.execute(
            """
            select c.relname, c.relrowsecurity, c.relforcerowsecurity
            from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = %s and c.relkind = 'r'
            order by 1
            """,
            (SCHEMA,),
        )
        rls = cur.fetchall()
        off = [name for name, enabled, _ in rls if not enabled]
        print(f"\nRLS: {len(rls) - len(off)}/{len(rls)} tabelas com RLS ativa")
        if off:
            failures.append(f"RLS desligada em: {off}")

        # --- policies --------------------------------------------------------
        cur.execute(
            "select tablename, policyname, roles::text, cmd "
            "from pg_policies where schemaname = %s order by 1",
            (SCHEMA,),
        )
        policies = cur.fetchall()
        print(f"POLICIES: {len(policies)}")
        exposed = [
            (t, p) for t, p, roles, _ in policies if "anon" in roles or "authenticated" in roles
        ]
        if exposed:
            failures.append(f"policy exposta a papel público: {exposed}")
        no_policy = set(t for t, _, _ in rls) - {t for t, _, _, _ in policies}
        if no_policy:
            failures.append(f"tabelas com RLS e sem policy de service_role: {sorted(no_policy)}")

        # --- privilégios públicos -------------------------------------------
        cur.execute(
            """
            select table_name, grantee, privilege_type
            from information_schema.role_table_grants
            where table_schema = %s and grantee in ('anon', 'authenticated')
            """,
            (SCHEMA,),
        )
        public_grants = cur.fetchall()
        print(f"PRIVILÉGIOS PARA anon/authenticated: {len(public_grants)}")
        if public_grants:
            failures.append(f"papéis públicos com privilégio: {public_grants[:5]}")

        # --- histórico -------------------------------------------------------
        cur.execute("select version, name from supabase_migrations.schema_migrations order by 1")
        print("\nMIGRATIONS REGISTRADAS:")
        for version, name in cur.fetchall():
            print(f"  {version}  {name}")

    print()
    if failures:
        print("SCHEMA_VALIDATION = FALHOU")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("SCHEMA_VALIDATION = OK")
    return 0


def fks_names(fks: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    return [(table, name) for table, name, _ in fks]


if __name__ == "__main__":
    raise SystemExit(main())

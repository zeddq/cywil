#!/usr/bin/env python3
"""
Compare two PostgreSQL schemas (public) and optionally add any columns
that are present only in LOCAL but missing in REMOTE.

Usage examples
--------------

# dry-run diff (default behaviour)
python compare_schema.py \
    --local  "postgresql://user:pass@localhost:5432/db1" \
    --remote "postgresql://user:pass@remote:5432/db2"

# diff + automatically add missing columns on the remote side
python compare_schema.py \
    --local  "postgresql://user:pass@localhost:5432/db1" \
    --remote "postgresql://user:pass@remote:5432/db2" \
    --create-missing
"""
import argparse
import sys
from typing import Dict, Tuple, Set, List
import psycopg2

ColInfo = Tuple[str, str, int | None, int | None, int | None]  # dtype, nullable, char_len, num_prec, num_scale


def fetch_schema(dsn: str) -> Dict[str, Dict[str, ColInfo]]:
    """
    Return {table: {column: (data_type, is_nullable, char_len, num_prec, num_scale)}}.
    """
    q = """
        SELECT table_name,
               column_name,
               data_type,
               is_nullable,
               character_maximum_length,
               numeric_precision,
               numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    schema: Dict[str, Dict[str, ColInfo]] = {}

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(q)
        for tbl, col, dtype, null, charlen, prec, scale in cur.fetchall():
            schema.setdefault(tbl, {})[col] = (dtype, null, charlen, prec, scale)

    return schema


def build_type(col: ColInfo) -> str:
    dtype, _, charlen, prec, scale = col

    if dtype == "character varying" and charlen:
        return f"varchar({charlen})"
    if dtype == "numeric" and prec and scale is not None:
        return f"numeric({prec},{scale})"
    if dtype == "timestamp without time zone":
        return "timestamp"
    # add more special-cases as needed
    return dtype  # fallback


def compare_and_sync(
    local: Dict[str, Dict[str, ColInfo]],
    remote: Dict[str, Dict[str, ColInfo]],
    remote_dsn: str,
    create_missing: bool,
) -> None:
    ltables, rtables = set(local), set(remote)

    # ─── Tables only on one side ────────────────────────────────────────────────
    only_local, only_remote = ltables - rtables, rtables - ltables
    if only_local:
        print("Tables only in LOCAL:", ", ".join(sorted(only_local)))
    if only_remote:
        print("Tables only in REMOTE:", ", ".join(sorted(only_remote)))

    # collect DDL statements to run (if any)
    ddl: List[str] = []

    # ─── Table-by-table comparison ─────────────────────────────────────────────
    shared_tables = ltables & rtables
    for table in sorted(shared_tables):
        lcols, rcols = local[table], remote[table]
        cols_only_local = set(lcols) - set(rcols)
        cols_only_remote = set(rcols) - set(lcols)

        if cols_only_local or cols_only_remote:
            print(f"\nTable {table}:")
        if cols_only_local:
            print("  Columns only in LOCAL:", ", ".join(sorted(cols_only_local)))
        if cols_only_remote:
            print("  Columns only in REMOTE:", ", ".join(sorted(cols_only_remote)))

        # gather DDL for missing columns on REMOTE
        if create_missing and cols_only_local:
            pieces = []
            for col in sorted(cols_only_local):
                dtype_sql = build_type(lcols[col])
                nullable_sql = "" if lcols[col][1] == "YES" else "NOT NULL"
                pieces.append(f'ADD COLUMN "{col}" {dtype_sql} {nullable_sql}'.rstrip())
            ddl.append(f'ALTER TABLE public."{table}"\n  ' + ",\n  ".join(pieces) + ";")


        # compare shared columns for type/nullability drift
        for col in sorted(set(lcols) & set(rcols)):
            if lcols[col] != rcols[col]:
                linfo, rinfo = lcols[col], rcols[col]
                print(
                    f"\nTable {table}, column {col} differs:"
                    f"\n  LOCAL : {build_type(linfo)}, nullable={linfo[1]}"
                    f"\n  REMOTE: {build_type(rinfo)}, nullable={rinfo[1]}"
                )

    # ─── Execute DDL on remote if requested ───────────────────────────────────
    if create_missing and ddl:
        print("\nApplying column additions to REMOTE …")
        try:
            with psycopg2.connect(remote_dsn) as conn:
                with conn.cursor() as cur:
                    for stmt in ddl:
                        print("  " + stmt.replace("\n", " "))
                        cur.execute(stmt)
                conn.commit()
        except psycopg2.Error as e:
            sys.exit(f"Failed to apply DDL – rolled back. Error: {e}")
        print("✔ Done – missing columns created.")
    elif create_missing:
        print("\nNothing to do – REMOTE already has all columns found in LOCAL.")


def main() -> None:
    p = argparse.ArgumentParser(description="Diff two PostgreSQL schemas (public).")
    p.add_argument("--local", required=True, help="Local DB URI")
    p.add_argument("--remote", required=True, help="Remote DB URI")
    p.add_argument(
        "-c", "--create-missing",
        action="store_true",
        help="Add columns that exist only in LOCAL to REMOTE"
    )
    args = p.parse_args()

    try:
        local_schema = fetch_schema(args.local)
        remote_schema = fetch_schema(args.remote)
    except psycopg2.Error as e:
        sys.exit(f"Connection/query error: {e}")

    compare_and_sync(
        local_schema,
        remote_schema,
        args.remote,
        create_missing=args.create_missing,
    )


if __name__ == "__main__":
    main()

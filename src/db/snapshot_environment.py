"""
Снимок состояния экспериментального стенда (этап 3).

Сохраняет в JSON всё, от чего зависят планы и время выполнения:
версию PostgreSQL, параметры планировщика, объёмы таблиц, индексы,
отпечаток статистики, параметры протокола измерений и версию корпуса.
Снимок делается перед сбором датасета и публикуется вместе с ним.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.db.connection import get_connection
from src.measure import protocol


DEFAULT_QUERIES_PATH = Path("data/queries/combined_tpch_queries.json")
DEFAULT_OUTPUT_PATH = Path("reports/stage3/environment.json")

TPCH_TABLES = [
    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
]

# Параметры, влияющие на выбор плана и время выполнения
PLANNER_SETTINGS = [
    "shared_buffers",
    "work_mem",
    "effective_cache_size",
    "maintenance_work_mem",
    "random_page_cost",
    "seq_page_cost",
    "cpu_tuple_cost",
    "cpu_index_tuple_cost",
    "cpu_operator_cost",
    "default_statistics_target",
    "jit",
    "max_parallel_workers_per_gather",
    "max_parallel_workers",
    "statement_timeout",
    "enable_hashjoin",
    "enable_mergejoin",
    "enable_nestloop",
    "enable_seqscan",
    "enable_indexscan",
    "enable_bitmapscan",
    "enable_sort",
    "enable_hashagg",
]


def fetch_all(cursor, sql: str, params=None):
    cursor.execute(sql, params)
    columns = [description.name for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_settings(cursor):
    rows = fetch_all(
        cursor,
        "SELECT name, setting, unit, source FROM pg_settings WHERE name = ANY(%s) ORDER BY name",
        (PLANNER_SETTINGS,),
    )
    return {row["name"]: row for row in rows}


def get_tables(cursor):
    tables = {}

    for table in TPCH_TABLES:
        cursor.execute(f"SELECT count(*) FROM {table}")
        row_count = cursor.fetchone()[0]

        stats = fetch_all(
            cursor,
            """
            SELECT
                pg_total_relation_size(relid) AS total_bytes,
                pg_relation_size(relid) AS heap_bytes,
                last_analyze,
                last_autoanalyze
            FROM pg_stat_user_tables
            WHERE relname = %s
            """,
            (table,),
        )[0]

        tables[table] = {
            "row_count": row_count,
            "total_bytes": stats["total_bytes"],
            "heap_bytes": stats["heap_bytes"],
            "last_analyze": str(stats["last_analyze"]),
            "last_autoanalyze": str(stats["last_autoanalyze"]),
        }

    return tables


def get_indexes(cursor):
    return fetch_all(
        cursor,
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY tablename, indexname
        """,
    )


def get_statistics_fingerprint(cursor):
    # ANALYZE строит статистику по случайной выборке строк,
    # поэтому после повторного импорта она может немного отличаться.
    # Отпечаток позволяет проверить, что датасет собран на той же статистике.
    rows = fetch_all(
        cursor,
        """
        SELECT tablename, attname, null_frac, avg_width, n_distinct,
               most_common_vals::text AS mcv, histogram_bounds::text AS histogram
        FROM pg_stats
        WHERE schemaname = 'public'
        ORDER BY tablename, attname
        """,
    )
    payload = json.dumps(rows, sort_keys=True, default=str).encode("utf-8")

    return {
        "columns_with_stats": len(rows),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def get_git_state():
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}

    return {"commit": commit, "dirty": dirty}


def get_corpus_info(path: Path):
    content = path.read_bytes()
    queries = json.loads(content)

    return {
        "path": str(path).replace("\\", "/"),
        "sha256": hashlib.sha256(content).hexdigest(),
        "queries": len(queries),
        "templates": len({query.get("template_id", query["id"]) for query in queries}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    with get_connection(autocommit=True) as connection:
        with connection.cursor() as cursor:
            # Настройки читаются после применения параметров сессии протокола,
            # то есть фиксируются те значения, с которыми идут измерения
            protocol.apply_session_settings(cursor)

            cursor.execute("SELECT version()")
            server_version = cursor.fetchone()[0]

            snapshot = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "git": get_git_state(),
                "client": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "cpu_count": os.cpu_count(),
                },
                "server_version": server_version,
                "settings": get_settings(cursor),
                "tables": get_tables(cursor),
                "indexes": get_indexes(cursor),
                "statistics": get_statistics_fingerprint(cursor),
                "protocol": {
                    "warmup_runs": protocol.WARMUP_RUNS,
                    "measured_runs": protocol.MEASURED_RUNS,
                    "statement_timeout_ms": protocol.STATEMENT_TIMEOUT_MS,
                    "unstable_cv": protocol.UNSTABLE_CV,
                    "session_settings": protocol.SESSION_SETTINGS,
                    "explain_sql": protocol.EXPLAIN_SQL,
                    "explain_analyze_sql": protocol.EXPLAIN_ANALYZE_SQL,
                },
                "corpus": get_corpus_info(args.queries),
            }

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as file:
        json.dump(snapshot, file, ensure_ascii=False, indent=2, default=str)

    lineitem_rows = snapshot["tables"]["lineitem"]["row_count"]
    print(f"Saved environment snapshot: {args.output}")
    print(f"PostgreSQL: {server_version}")
    print(f"lineitem rows: {lineitem_rows} (SF ~ {lineitem_rows / 6_001_215:.2f})")
    print(f"Indexes: {len(snapshot['indexes'])}")
    print(f"Statistics sha256: {snapshot['statistics']['sha256'][:16]}...")


if __name__ == "__main__":
    main()

import argparse
import json
from pathlib import Path

import pandas as pd
import psycopg

from src.checks.check_collection import validate_collection
from src.db.connection import get_connection
from src.db.workload import load_queries
from src.features.columns import FEATURE_GROUPS, META_COLUMNS, TARGET_COLUMNS
from src.features.extract_features import (
    extract_plan_features,
    extract_sql_features,
    normalize_sql,
)
from src.measure.protocol import (
    MEASURED_RUNS,
    WARMUP_RUNS,
    aggregate_runs,
    apply_session_settings,
    iter_query_runs,
    run_explain,
)


DEFAULT_QUERIES_PATH = Path("data/queries/combined_tpch_queries.json")
DEFAULT_OUTPUT_PATH = Path("data/processed/query_dataset.csv")
DEFAULT_MEASUREMENTS_PATH = Path("data/processed/measurements.csv")
DEFAULT_PLANS_PATH = Path("data/processed/plans.jsonl")


def collect_row(cursor, query: dict, warmup_runs: int, measured_runs: int):
    key = query["id"]
    row = {
        "query_id": key,
        "template_id": query.get("template_id", key),
        "source": query.get("source"),
        "query_type": query.get("query_type"),
        "expected_complexity": query.get("expected_complexity"),
        "sql_text": query.get("sql"),
        "status": "ok",
        "error": None,
        "execution_time_ms": None,
    }
    runs = []
    plans = {"query_id": key, "explain": None, "explain_analyze": None}
    phase = "подготовка SQL"
    try:
        sql = normalize_sql(query["sql"])
        phase = "EXPLAIN"
        plans["explain"] = run_explain(cursor, sql)
        phase = "извлечение признаков"
        row.update(extract_sql_features(sql))
        row.update(extract_plan_features(plans["explain"]))
        phase = "запуск 0"
        for run, plan in iter_query_runs(cursor, sql, warmup_runs, measured_runs):
            runs.append({"query_id": key, **run})
            if not run["is_warmup"] and plans["explain_analyze"] is None:
                plans["explain_analyze"] = plan
            phase = f"запуск {len(runs)}"
        phase = "агрегирование повторов"
        row.update(aggregate_runs(runs))
    except Exception as error:
        row["status"] = "timeout" if isinstance(error, psycopg.errors.QueryCanceled) else "error"
        row["error"] = f"{phase}: {type(error).__name__}: {error}"
        row["measured_runs"] = sum(not run["is_warmup"] for run in runs)

    return row, runs, plans


def assign_labels(dataframe: pd.DataFrame, threshold_ms: float, label_quantile):
    ok = dataframe["status"] == "ok"

    if ok.any() and label_quantile is not None:
        threshold_ms = dataframe.loc[ok, "execution_time_ms"].quantile(label_quantile)
        print(f"Label threshold by quantile {label_quantile}: {threshold_ms:.4f} ms")

    dataframe["label"] = pd.NA
    dataframe.loc[ok, "label"] = (
        dataframe.loc[ok, "execution_time_ms"] > threshold_ms
    ).astype(int)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--measurements-output", type=Path, default=DEFAULT_MEASUREMENTS_PATH)
    parser.add_argument("--plans-output", type=Path, default=DEFAULT_PLANS_PATH)
    parser.add_argument("--warmup-runs", type=int, default=WARMUP_RUNS)
    parser.add_argument("--runs", type=int, default=MEASURED_RUNS)
    parser.add_argument("--limit-per-template", type=int, default=None)
    parser.add_argument("--threshold-ms", type=float, default=1000.0)
    parser.add_argument(
        "--label-quantile", type=float, default=None,
        help="Описательная метка CSV по всему корпусу. Для обучения порог вычисляется отдельно на train.",
    )
    args = parser.parse_args()

    queries = load_queries(args.queries, args.limit_per_template)

    if args.warmup_runs < 0 or args.runs < 1:
        parser.error("--warmup-runs должен быть >= 0, --runs должен быть >= 1")
    expected_ids = [q["id"] for q in queries]
    if not expected_ids or len(set(expected_ids)) != len(expected_ids):
        parser.error("Для сбора нужен непустой список запросов с уникальными id")

    rows = []
    all_runs = []
    all_plans = []
    with get_connection(autocommit=True) as connection:
        with connection.cursor() as cursor:
            apply_session_settings(cursor)
            for index, query in enumerate(queries, start=1):
                row, runs, plans = collect_row(cursor, query, args.warmup_runs, args.runs)
                rows.append(row)
                all_runs.extend(runs)
                all_plans.append(plans)
                detail = row["error"] or f"median={row['execution_time_ms']:.2f} ms"
                print(f"[{index}/{len(queries)}] {query['id']}: {row['status']} {detail}", flush=True)

    # Схемы CSV сохраняются даже при сбое всех запросов до первого замера.
    features = [name for group in FEATURE_GROUPS.values() for name in group]
    dataframe = pd.DataFrame(rows, columns=[*META_COLUMNS, *features, *TARGET_COLUMNS])
    assign_labels(dataframe, args.threshold_ms, args.label_quantile)
    measurements = pd.DataFrame(all_runs, columns=[
        "query_id", "run_index", "is_warmup", "execution_time_ms", "planning_time_ms",
    ])
    validate_collection(
        expected_ids, dataframe, measurements, [p["query_id"] for p in all_plans],
        args.warmup_runs, args.runs,
    )
    for path in [args.output, args.measurements_output, args.plans_output]:
        path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(args.output, index=False)
    measurements.to_csv(args.measurements_output, index=False)
    with args.plans_output.open("w", encoding="utf-8") as file:
        for plan in all_plans:
            file.write(json.dumps(plan, ensure_ascii=False) + "\n")

    print(f"Saved dataset: {args.output}")
    print(f"Saved measurements: {args.measurements_output}")
    print(f"Saved plans: {args.plans_output}")
    print(f"Rows: {len(dataframe)}")
    print("Status distribution:")
    print(dataframe["status"].value_counts())
    print("Label distribution:")
    print(dataframe["label"].value_counts())


if __name__ == "__main__":
    main()

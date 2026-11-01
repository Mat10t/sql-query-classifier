import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd
import psycopg

from src.db.connection import get_connection
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
    measure_query,
    run_explain,
)


DEFAULT_QUERIES_PATH = Path("data/queries/combined_tpch_queries.json")
DEFAULT_OUTPUT_PATH = Path("data/processed/query_dataset.csv")
DEFAULT_MEASUREMENTS_PATH = Path("data/processed/measurements.csv")
DEFAULT_PLANS_PATH = Path("data/processed/plans.jsonl")


def load_queries(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def limit_per_template(queries: list, limit: int) -> list:
    # Берём первые limit запросов каждого шаблона (для эксперимента с повторами)
    counts = defaultdict(int)
    selected = []

    for query in queries:
        template_id = query.get("template_id", query["id"])

        if counts[template_id] < limit:
            selected.append(query)
            counts[template_id] += 1

    return selected


def collect_row(cursor, query: dict, warmup_runs: int, measured_runs: int):
    sql = normalize_sql(query["sql"])

    # Признаки строятся только по EXPLAIN без выполнения запроса
    explain_json = run_explain(cursor, sql)

    row = {
        "query_id": query["id"],
        "template_id": query.get("template_id", query["id"]),
        "source": query.get("source"),
        "query_type": query.get("query_type"),
        "expected_complexity": query.get("expected_complexity"),
        "sql_text": query["sql"],

        **extract_sql_features(sql),
        **extract_plan_features(explain_json),
    }

    plans = {
        "query_id": query["id"],
        "explain": explain_json,
        "explain_analyze": None,
    }

    try:
        measurement = measure_query(cursor, sql, warmup_runs, measured_runs)
    except psycopg.errors.QueryCanceled:
        row["status"] = "timeout"
        return row, [], plans

    runs = [{"query_id": query["id"], **run} for run in measurement["runs"]]
    plans["explain_analyze"] = measurement["analyze_json"]

    row["status"] = "ok"
    row.update(aggregate_runs(measurement["runs"]))

    return row, runs, plans


def assign_labels(dataframe: pd.DataFrame, threshold_ms: float, label_quantile):
    ok = dataframe["status"] == "ok"

    if label_quantile is not None:
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
    parser.add_argument("--label-quantile", type=float, default=None)
    args = parser.parse_args()

    queries = load_queries(args.queries)

    if args.limit_per_template is not None:
        queries = limit_per_template(queries, args.limit_per_template)

    rows = []
    all_runs = []

    for path in [args.output, args.measurements_output, args.plans_output]:
        path.parent.mkdir(parents=True, exist_ok=True)

    with get_connection(autocommit=True) as connection:
        with connection.cursor() as cursor:
            apply_session_settings(cursor)

            with args.plans_output.open("w", encoding="utf-8") as plans_file:
                for index, query in enumerate(queries, start=1):
                    print(f"[{index}/{len(queries)}] {query['id']}", flush=True)

                    try:
                        row, runs, plans = collect_row(
                            cursor, query, args.warmup_runs, args.runs
                        )
                    except Exception as error:
                        print(f"  ERROR: {error}")
                        continue

                    rows.append(row)
                    all_runs.extend(runs)
                    plans_file.write(json.dumps(plans, ensure_ascii=False) + "\n")

                    if row["status"] == "ok":
                        print(
                            f"  median={row['execution_time_ms']:.2f} ms, "
                            f"cv={row['exec_time_cv']:.3f}"
                        )
                    else:
                        print(f"  status={row['status']}")

    dataframe = pd.DataFrame(rows)
    assign_labels(dataframe, args.threshold_ms, args.label_quantile)

    dataframe.to_csv(args.output, index=False)
    pd.DataFrame(all_runs).to_csv(args.measurements_output, index=False)

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

import argparse
import json
import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

from src.features.extract_features import (
    extract_execution_metrics,
    extract_plan_features,
    extract_sql_features,
    normalize_sql,
)


DEFAULT_QUERIES_PATH = Path("data/queries/generated_tpch_queries.json")
DEFAULT_OUTPUT_PATH = Path("data/processed/query_dataset.csv")


def get_connection():
    load_dotenv()

    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def load_queries(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def run_explain(cursor, sql: str):
    cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}")
    return cursor.fetchone()[0]


def run_explain_analyze(cursor, sql: str):
    cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
    return cursor.fetchone()[0]


def collect_row(cursor, query: dict, threshold_ms: float):
    sql = normalize_sql(query["sql"])

    explain_json = run_explain(cursor, sql)
    explain_analyze_json = run_explain_analyze(cursor, sql)

    sql_features = extract_sql_features(sql)
    plan_features = extract_plan_features(explain_json)
    execution_metrics = extract_execution_metrics(explain_analyze_json)

    execution_time_ms = execution_metrics["execution_time_ms"]
    label = 1 if execution_time_ms > threshold_ms else 0

    return {
        "query_id": query["id"],
        "query_type": query.get("query_type"),
        "expected_complexity": query.get("expected_complexity"),
        "sql_text": query["sql"],

        **sql_features,
        **plan_features,
        **execution_metrics,

        "label": label,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--threshold-ms", type=float, default=1000.0)
    parser.add_argument("--label-quantile", type=float, default=None)
    args = parser.parse_args()

    queries = load_queries(args.queries)
    rows = []

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for index, query in enumerate(queries, start=1):
                print(f"[{index}/{len(queries)}] {query['id']}")

                try:
                    row = collect_row(cursor, query, args.threshold_ms)
                    rows.append(row)

                    print(
                        f"  execution_time_ms={row['execution_time_ms']:.2f}, "
                        f"label={row['label']}"
                    )

                except Exception as error:
                    print(f"  ERROR: {error}")
                    connection.rollback()

    dataframe = pd.DataFrame(rows)
    
    if args.label_quantile is not None:
        threshold = dataframe["execution_time_ms"].quantile(args.label_quantile)
        dataframe["label"] = (dataframe["execution_time_ms"] > threshold).astype(int)

        print(f"Label threshold by quantile {args.label_quantile}: {threshold:.4f} ms")
        print("Updated label distribution:")
        print(dataframe["label"].value_counts())

    dataframe.to_csv(args.output, index=False)

    print(f"Saved dataset: {args.output}")
    print(f"Rows: {len(dataframe)}")

    if len(dataframe) > 0:
        print("Label distribution:")
        print(dataframe["label"].value_counts())


if __name__ == "__main__":
    main()

import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv


DEFAULT_QUERIES_PATH = Path("data/queries/combined_tpch_queries.json")


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


def check_query(cursor, query):
    sql = query["sql"]

    cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}")
    explain_result = cursor.fetchone()[0]

    plan = explain_result[0]["Plan"]

    print(f"{query['id']}: OK")
    print(f"  type: {query.get('query_type', '-')}")
    print(f"  expected_complexity: {query['expected_complexity']}")
    print(f"  node_type: {plan.get('Node Type')}")
    print(f"  total_cost: {plan.get('Total Cost')}")
    print(f"  plan_rows: {plan.get('Plan Rows')}")


def main():
    queries_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_QUERIES_PATH
    queries = load_queries(queries_path)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for query in queries:
                check_query(cursor, query)

    print("All queries checked successfully")


if __name__ == "__main__":
    main()
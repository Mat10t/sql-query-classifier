"""
Выгрузка примеров EXPLAIN / EXPLAIN ANALYZE для отчёта (этап 3).

Для каждого выбранного запроса сохраняются SQL-текст, план без выполнения
(из него строятся признаки) и план с ANALYZE (из него берётся только t(q)).
"""

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_DATASET_PATH = Path("data/processed/query_dataset.csv")
DEFAULT_PLANS_PATH = Path("data/processed/plans.jsonl")
DEFAULT_OUTPUT_DIR = Path("reports/stage3/examples")
DEFAULT_QUERY_IDS = ["q0001", "tpch_s101_q03"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--plans", type=Path, default=DEFAULT_PLANS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--query-ids", nargs="+", default=DEFAULT_QUERY_IDS)
    args = parser.parse_args()

    dataset = pd.read_csv(args.dataset).set_index("query_id")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with args.plans.open("r", encoding="utf-8") as file:
        plans = {record["query_id"]: record for record in map(json.loads, file)}

    for query_id in args.query_ids:
        row = dataset.loc[query_id]

        (args.output_dir / f"{query_id}.sql").write_text(row["sql_text"], encoding="utf-8")

        for kind in ["explain", "explain_analyze"]:
            path = args.output_dir / f"{query_id}.{kind}.json"

            with path.open("w", encoding="utf-8") as file:
                json.dump(plans[query_id][kind], file, ensure_ascii=False, indent=2)

        print(
            f"{query_id}: total_cost={row['total_cost']}, "
            f"t(q)={row['execution_time_ms']:.3f} ms -> {args.output_dir}"
        )


if __name__ == "__main__":
    main()

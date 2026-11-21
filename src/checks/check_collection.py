"""Сверка результатов сбора с ожидаемыми идентификаторами и протоколом повторов."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from statistics import median

import pandas as pd

from src.db.workload import load_queries
from src.measure.protocol import WARMUP_RUNS, MEASURED_RUNS


def check_ids(expected, actual, name):
    counts = Counter(actual)
    missing = expected - counts.keys()
    extra = counts.keys() - expected
    duplicates = [key for key, count in counts.items() if count > 1]
    if missing or extra or duplicates:
        raise ValueError(
            f"{name}: пропущены {sorted(missing)}, лишние {sorted(extra)}, повторы {sorted(duplicates)}"
        )


def validate_collection(expected_ids, dataset, measurements, plan_ids, warmups, measured):
    if warmups < 0 or measured < 1 or not expected_ids:
        raise ValueError("Проверьте корпус и параметры повторов")
    expected = set(expected_ids)
    check_ids(expected, expected_ids, "Корпус")
    check_ids(expected, dataset["query_id"], "Результаты")
    check_ids(expected, plan_ids, "Планы")
    extra = set(measurements["query_id"]) - expected
    if extra:
        raise ValueError(f"Журнал содержит лишние query_id: {sorted(extra)}")

    by_query = {key: group for key, group in measurements.groupby("query_id")}
    empty = measurements.iloc[:0]
    for row in dataset.to_dict("records"):
        key = row["query_id"]
        group = by_query.get(key, empty).sort_values("run_index")
        size = len(group)
        if list(group["run_index"]) != list(range(size)) or size > warmups + measured:
            raise ValueError(f"{key}: нарушена нумерация повторов")
        if list(group["is_warmup"]) != [i < warmups for i in range(size)]:
            raise ValueError(f"{key}: нарушен порядок прогрева")
        times = group["execution_time_ms"].tolist()
        if any(not math.isfinite(t) or t < 0 for t in times):
            raise ValueError(f"{key}: некорректное время в журнале")
        valid = times[warmups:]
        if row["measured_runs"] != len(valid):
            raise ValueError(f"{key}: measured_runs расходится с журналом")
        if row["status"] == "ok":
            if size != warmups + measured or not math.isclose(row["execution_time_ms"], median(valid)):
                raise ValueError(f"{key}: неполная серия или неверная медиана")
        elif row["status"] in ("timeout", "error"):
            reason = row.get("error")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{key}: отсутствует причина сбоя")
            if pd.notna(row["execution_time_ms"]) or pd.notna(row.get("label")):
                raise ValueError(f"{key}: при сбое цель и метка должны быть пустыми")
        else:
            raise ValueError(f"{key}: неизвестный статус {row['status']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, default=Path("data/queries/combined_tpch_queries.json"))
    parser.add_argument("--dataset", type=Path, default=Path("data/processed/query_dataset.csv"))
    parser.add_argument("--measurements", type=Path, default=Path("data/processed/measurements.csv"))
    parser.add_argument("--plans", type=Path, default=Path("data/processed/plans.jsonl"))
    parser.add_argument("--warmup-runs", type=int, default=WARMUP_RUNS)
    parser.add_argument("--runs", type=int, default=MEASURED_RUNS)
    parser.add_argument("--limit-per-template", type=int)
    args = parser.parse_args()
    queries = load_queries(args.queries, args.limit_per_template)
    dataset = pd.read_csv(args.dataset)
    measurements = pd.read_csv(args.measurements)
    with args.plans.open(encoding="utf-8") as file:
        plan_ids = [json.loads(line)["query_id"] for line in file]
    validate_collection(
        [q["id"] for q in queries], dataset, measurements, plan_ids, args.warmup_runs, args.runs
    )
    print(f"OK: запросов {len(dataset)}, записей планов {len(plan_ids)}, завершённых повторов {len(measurements)}")
    print(dataset["status"].value_counts().to_string())


if __name__ == "__main__":
    main()

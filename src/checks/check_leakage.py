"""
Проверка отсутствия фактических метрик выполнения во входных признаках.

1. Признаки датасета — ровно те, что возвращают extract_sql_features
   и extract_plan_features (никаких лишних колонок).
2. В сохранённых планах EXPLAIN нет полей, появляющихся только при ANALYZE.
3. Признаки, пересчитанные из сохранённых EXPLAIN-планов и SQL-текста,
   совпадают с признаками в датасете.

Завершается с кодом 1, если хотя бы одна проверка не пройдена.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.columns import get_feature_columns
from src.features.extract_features import (
    extract_plan_features,
    extract_sql_features,
    normalize_sql,
)


DEFAULT_DATASET_PATH = Path("data/processed/query_dataset.csv")
DEFAULT_PLANS_PATH = Path("data/processed/plans.jsonl")

# Поля плана, которые PostgreSQL добавляет только при EXPLAIN ANALYZE
ANALYZE_ONLY_KEYS = {
    "Actual Startup Time",
    "Actual Total Time",
    "Actual Rows",
    "Actual Loops",
    "Execution Time",
    "Shared Hit Blocks",
    "Shared Read Blocks",
}


def collect_keys(value, keys: set):
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            collect_keys(child, keys)
    elif isinstance(value, list):
        for child in value:
            collect_keys(child, keys)


def load_plans(path: Path) -> dict:
    plans = {}

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            plans[record["query_id"]] = record

    return plans


def check_feature_set(dataset: pd.DataFrame, plans: dict) -> list[str]:
    sample = dataset.iloc[0]
    expected = set(extract_sql_features(normalize_sql(sample["sql_text"])))
    expected |= set(extract_plan_features(plans[sample["query_id"]]["explain"]))

    actual = set(get_feature_columns(dataset.columns))
    errors = []

    if actual - expected:
        errors.append(f"Лишние колонки среди признаков: {sorted(actual - expected)}")

    if expected - actual:
        errors.append(f"В датасете нет признаков: {sorted(expected - actual)}")

    return errors


def check_explain_plans(plans: dict) -> list[str]:
    errors = []

    for query_id, record in plans.items():
        keys = set()
        collect_keys(record["explain"], keys)
        leaked = keys & ANALYZE_ONLY_KEYS

        if leaked:
            errors.append(f"{query_id}: план для признаков содержит {sorted(leaked)}")

    return errors


def check_recomputed_features(dataset: pd.DataFrame, plans: dict) -> list[str]:
    feature_columns = get_feature_columns(dataset.columns)
    errors = []

    for _, row in dataset.iterrows():
        sql = normalize_sql(row["sql_text"])
        features = {
            **extract_sql_features(sql),
            **extract_plan_features(plans[row["query_id"]]["explain"]),
        }

        for column in feature_columns:
            if not np.isclose(float(features[column]), float(row[column])):
                errors.append(
                    f"{row['query_id']}.{column}: в датасете {row[column]}, "
                    f"пересчитано {features[column]}"
                )

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--plans", type=Path, default=DEFAULT_PLANS_PATH)
    args = parser.parse_args()

    dataset = pd.read_csv(args.dataset)
    try:
        get_feature_columns(dataset.columns)
    except ValueError as error:
        sys.exit(f"FAIL  {error}")
    plans = load_plans(args.plans)
    features = get_feature_columns(dataset.columns)
    # Проверяем и частичные серии, если сборщик успел сохранить признаки.
    if "status" in dataset:
        dataset = dataset.loc[dataset["status"].eq("ok") | dataset[features].notna().all(axis=1)]
    if dataset.empty:
        sys.exit("Нет запросов с полным набором признаков для проверки")

    checks = [
        ("Набор признаков совпадает с выходом экстракторов", check_feature_set(dataset, plans)),
        ("Планы для признаков получены без ANALYZE", check_explain_plans(plans)),
        ("Признаки воспроизводятся из EXPLAIN и SQL-текста", check_recomputed_features(dataset, plans)),
    ]

    failed = False

    for title, errors in checks:
        if errors:
            failed = True
            print(f"FAIL  {title}")
            for error in errors[:10]:
                print(f"      {error}")
        else:
            print(f"OK    {title}")

    print(f"\nПризнаков: {len(get_feature_columns(dataset.columns))}, запросов: {len(dataset)}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

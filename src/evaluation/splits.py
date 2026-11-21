"""Фиксированные выборки для сравнения моделей на корпусе измеренных запросов."""

import argparse
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from src.features.columns import get_feature_columns


DATASET_PATH = Path("data/processed/query_dataset.csv")
SPLIT_PATH = Path("reports/stage4/splits.csv")
MODES = ("template", "random")
SEED = 42
TEST_SIZE = 0.25


def eligible_rows(data):
    if "status" in data:
        data = data.loc[data["status"].eq("ok")]
    keys = data[["query_id", "template_id"]]
    if keys.isna().any().any() or keys.eq("").any().any():
        raise ValueError("У каждого запроса должны быть query_id и template_id")
    if keys["query_id"].duplicated().any():
        raise ValueError("В корпусе повторяется query_id")
    return data.sort_values("query_id").reset_index(drop=True)


def build_splits(data):
    rows = eligible_rows(data)[["query_id", "template_id"]].copy()
    for mode, key in (("template", "template_id"), ("random", "query_id")):
        items = sorted(rows[key].unique())
        _, test = train_test_split(items, test_size=TEST_SIZE, random_state=SEED)
        rows[mode] = rows[key].isin(test).map({True: "test", False: "train"})
    return rows


def validate_splits(data, assignments):
    rows = eligible_rows(data)
    saved = assignments.sort_values("query_id").reset_index(drop=True)
    if not rows[["query_id", "template_id"]].equals(saved[["query_id", "template_id"]]):
        raise ValueError("Состав разбиения не совпадает с query_id и template_id корпуса")
    for mode in MODES:
        if set(saved[mode]) != {"train", "test"}:
            raise ValueError(f"Некорректный состав train/test в режиме {mode}")
    sizes = saved.groupby("template_id")["template"].nunique()
    overlap = sizes[sizes != 1].index.tolist()
    if overlap:
        raise ValueError(f"Шаблоны одновременно в train и test: {overlap}")
    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--splits", type=Path, default=SPLIT_PATH)
    parser.add_argument("--write", action="store_true", help="Создать файл для нового корпуса")
    args = parser.parse_args()
    data = pd.read_csv(args.dataset)
    features = get_feature_columns(data.columns)
    expected = build_splits(data)
    if args.write:
        args.splits.parent.mkdir(parents=True, exist_ok=True)
        expected.to_csv(args.splits, mode="x", index=False)
    saved = validate_splits(data, pd.read_csv(args.splits))
    if not saved.equals(expected):
        raise ValueError("Сохранённые назначения отличаются от разбиения с seed 42")
    print(f"Признаков: {len(features)}, запросов: {len(saved)}, seed: {SEED}")
    for mode in MODES:
        counts = saved.groupby(mode).agg(queries=("query_id", "size"), templates=("template_id", "nunique"))
        overlap = saved.groupby("template_id")[mode].nunique().gt(1).sum()
        print(f"{mode}: общих шаблонов {overlap}")
        print(counts.to_string())


if __name__ == "__main__":
    main()

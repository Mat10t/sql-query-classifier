"""Покрытие диапазонов длительности и контрольное сравнение для корпуса v2."""

import argparse
import json
from pathlib import Path

import pandas as pd

from src.db.build_extended_workload import SPLITS
from src.evaluation.baselines import errors, run
from src.evaluation.splits import DATASET_PATH, SPLIT_PATH, eligible_rows, validate_splits


def coverage(rows):
    times = rows["execution_time_ms"]
    middle = rows.loc[times.ge(1) & times.lt(100)]
    return {
        "queries": len(rows),
        "templates": int(rows.template_id.nunique()),
        "min_ms": float(times.min()) if len(times) else None,
        "max_ms": float(times.max()) if len(times) else None,
        "under_1_ms": int(times.lt(1).sum()),
        "1_to_10_ms": int((times.ge(1) & times.lt(10)).sum()),
        "10_to_100_ms": int((times.ge(10) & times.lt(100)).sum()),
        "at_least_100_ms": int(times.ge(100).sum()),
        "1_to_100_ms": len(middle),
        "templates_in_1_to_100_ms": int(middle.template_id.nunique()),
    }


def summarize(base, expanded, base_manifest, expanded_manifest):
    old = validate_splits(base, base_manifest)
    manifest = validate_splits(expanded, expanded_manifest)
    retained = manifest.query_id.isin(old.query_id)
    if not manifest.loc[retained].reset_index(drop=True).equals(old):
        raise ValueError("Старые назначения train/test должны сохраниться полностью")
    rows = eligible_rows(expanded).merge(manifest, on=["query_id", "template_id"], validate="one_to_one")
    added = ~rows.query_id.isin(old.query_id)
    original_series = eligible_rows(base).merge(old, on=["query_id", "template_id"], validate="one_to_one")
    summary = {
        "original_series": coverage(original_series),
        "expanded_series": coverage(rows),
        "retained_queries_remeasured": coverage(rows.loc[~added]),
        "added_queries": coverage(rows.loc[added]),
        "template_train": coverage(rows.loc[rows.template.eq("train")]),
        "template_test": coverage(rows.loc[rows.template.eq("test")]),
        "original_template_test": coverage(original_series.loc[original_series.template.eq("test")]),
        "added_templates": {name: coverage(group) for name, group in rows.loc[added].groupby("template_id")},
    }

    # Оба варианта обучаем на временах одной новой сессии. Тест одинаков для обоих.
    original_ids = expanded.query_id.isin(old.query_id)
    _, old_predictions = run(expanded.loc[original_ids], old)
    _, new_predictions = run(expanded, manifest)
    common_test = old.loc[old.template.eq("test"), "query_id"]
    comparison = {}
    for name, predictions in [("original_train", old_predictions), ("expanded_train", new_predictions)]:
        part = predictions.loc[predictions.split.eq("template")].set_index("query_id").loc[common_test]
        comparison[name] = errors(part.predicted_ms, part.execution_time_ms)
    summary["same_test_remeasured"] = {"queries": len(common_test), **comparison}

    summary["constant_by_split"] = {}
    for mode in ("template", "random"):
        train_median = float(rows.loc[rows[mode].eq("train"), "execution_time_ms"].median())
        test_times = rows.loc[rows[mode].eq("test"), "execution_time_ms"]
        summary["constant_by_split"][mode] = {
            "train_median_ms": train_median,
            **errors([train_median] * len(test_times), test_times),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--dataset", type=Path, default=Path("data/processed/v2/query_dataset.csv"))
    parser.add_argument("--base-splits", type=Path, default=SPLIT_PATH)
    parser.add_argument("--splits", type=Path, default=SPLITS)
    parser.add_argument("--output", type=Path, default=SPLITS.parent / "coverage.json")
    args = parser.parse_args()
    summary = summarize(pd.read_csv(args.base_dataset), pd.read_csv(args.dataset),
                        pd.read_csv(args.base_splits), pd.read_csv(args.splits))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for key in ("original_series", "expanded_series", "added_queries", "template_test"):
        counts = summary[key]
        print(f"{key}: {counts['1_to_100_ms']} из {counts['queries']} запросов от 1 до 100 мс")


if __name__ == "__main__":
    main()

"""Базовые оценки по Total Cost на фиксированных тестовых выборках этапа 4."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.evaluation.ranking import pairwise_summary, ranking_metrics
from src.evaluation.splits import DATASET_PATH, MODES, SPLIT_PATH, eligible_rows, validate_splits
from src.features.columns import get_feature_columns


def errors(predicted, actual):
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
    }


def score_order(predicted, test):
    actual = test["execution_time_ms"]
    ranks = ranking_metrics(predicted, actual, include_pair_count=True)
    # У постоянной величины ранговая корреляция не определена.
    result = {key: value if np.isfinite(value) else None for key, value in ranks.items()}
    result["separated_runs"] = pairwise_summary(
        predicted, actual, bounds=(test["exec_time_min_ms"], test["exec_time_max_ms"])
    )
    return result


def evaluate(rows, assignments, mode):
    train = rows.loc[assignments.index[assignments[mode].eq("train")]]
    test = rows.loc[assignments.index[assignments[mode].eq("test")]]
    model = LinearRegression().fit(train[["total_cost"]], np.log1p(train["execution_time_ms"]))
    log_prediction = np.maximum(0.0, model.predict(test[["total_cost"]]))
    with np.errstate(over="raise"):
        predicted_ms = np.expm1(log_prediction)
    actual = test["execution_time_ms"]
    predictions = test[[
        "template_id", "execution_time_ms", "exec_time_min_ms", "exec_time_max_ms", "total_cost"
    ]].copy()
    predictions["predicted_ms"] = predicted_ms
    metrics = {
        "train_queries": len(train), "test_queries": len(test),
        "train_templates": int(train["template_id"].nunique()),
        "test_templates": int(test["template_id"].nunique()),
        "total_cost": score_order(test["total_cost"], test),
        "regression": {
            "intercept": float(model.intercept_), "coefficient": float(model.coef_[0]),
            "errors_ms": errors(predicted_ms, actual),
            "errors_log1p_ms": errors(log_prediction, np.log1p(actual)),
            "ranking": score_order(predicted_ms, test),
        },
    }
    return metrics, predictions


def run(data, manifest):
    get_feature_columns(data.columns)
    assignments = validate_splits(data, manifest).set_index("query_id")
    rows = eligible_rows(data).set_index("query_id")
    values = rows[["total_cost", "execution_time_ms", "exec_time_min_ms", "exec_time_max_ms"]]
    if not np.isfinite(values).all().all() or (values < 0).any().any():
        raise ValueError("Стоимость и время успешного запроса должны быть конечными и неотрицательными")
    if not rows["execution_time_ms"].between(rows["exec_time_min_ms"], rows["exec_time_max_ms"]).all():
        raise ValueError("Медиана времени вне диапазона повторов")
    metrics = {}
    predictions = []
    for mode in MODES:
        metrics[mode], test = evaluate(rows, assignments, mode)
        predictions.append(test.reset_index().assign(split=mode))
    return metrics, pd.concat(predictions, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--splits", type=Path, default=SPLIT_PATH)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/stage5"))
    args = parser.parse_args()
    metrics, predictions = run(pd.read_csv(args.dataset), pd.read_csv(args.splits))
    report = json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(args.output_dir / "predictions.csv", index=False)
    (args.output_dir / "metrics.json").write_text(report + "\n", encoding="utf-8")
    for mode, result in metrics.items():
        ms = result["regression"]["errors_ms"]
        print(f"{mode}: test {result['test_queries']}, MAE {ms['mae']:.2f} мс, RMSE {ms['rmse']:.2f} мс")


if __name__ == "__main__":
    main()

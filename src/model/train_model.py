import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, roc_auc_score
from sklearn.preprocessing import StandardScaler

from src.evaluation.splits import DATASET_PATH, MODES, SEED, SPLIT_PATH, eligible_rows, validate_splits
from src.features.columns import FEATURE_GROUPS, get_feature_columns


def binary_labels(train_time, test_time):
    for times in (train_time, test_time):
        if not np.isfinite(times).all() or (times < 0).any():
            raise ValueError("Время успешного запроса должно быть конечным неотрицательным числом")
    threshold = float(train_time.quantile(0.75))
    return threshold, (train_time > threshold).astype(int), (test_time > threshold).astype(int)


def train(data, assignments, mode, groups, model_dir, reports_dir):
    features = get_feature_columns(data.columns, groups)
    saved = validate_splits(data, assignments).set_index("query_id")
    rows = eligible_rows(data).set_index("query_id")
    train_ids = saved.index[saved[mode] == "train"]
    test_ids = saved.index[saved[mode] == "test"]
    threshold, y_train, y_test = binary_labels(
        rows.loc[train_ids, "execution_time_ms"], rows.loc[test_ids, "execution_time_ms"]
    )
    if y_train.nunique() != 2:
        raise ValueError("После назначения порога в train нужен хотя бы один запрос каждого класса")

    scaler = StandardScaler()
    x_train = scaler.fit_transform(rows.loc[train_ids, features])
    x_test = scaler.transform(rows.loc[test_ids, features])
    model = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=SEED)
    model.fit(x_train, y_train)
    prediction = model.predict(x_test)
    probability = model.predict_proba(x_test)[:, 1]
    metrics = {
        "dataset_rows": len(rows),
        "split": mode,
        "groups": groups,
        "train_queries": len(train_ids),
        "test_queries": len(test_ids),
        "threshold_ms": threshold,
        "threshold_quantile_train": 0.75,
        "label_distribution": {
            str(k): int(v) for k, v in pd.concat([y_train, y_test]).value_counts().sort_index().items()
        },
        "accuracy": float(accuracy_score(y_test, prediction)),
        "roc_auc": float(roc_auc_score(y_test, probability)) if y_test.nunique() == 2 else None,
        "confusion_matrix": confusion_matrix(y_test, prediction, labels=[0, 1]).tolist(),
        "classification_report": classification_report(
            y_test, prediction, labels=[0, 1], output_dict=True, zero_division=0
        ),
    }
    model_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_dir / "query_classifier.joblib")
    joblib.dump(scaler, model_dir / "scaler.joblib")
    (model_dir / "feature_columns.json").write_text(json.dumps(features, indent=2), encoding="utf-8")
    (reports_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    pd.DataFrame({
        "feature": features,
        "coefficient": model.coef_[0],
        "abs_coefficient": abs(model.coef_[0]),
    }).sort_values("abs_coefficient", ascending=False).to_csv(reports_dir / "feature_importance.csv", index=False)
    print(f"Разбиение: {mode}, train: {len(train_ids)}, test: {len(test_ids)}")
    print(f"Порог по train: {threshold:g} мс. Accuracy: {metrics['accuracy']:.4f}, ROC-AUC: {metrics['roc_auc']}")
    print(f"Метрики: {reports_dir / 'metrics.json'}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--splits", type=Path, default=SPLIT_PATH)
    parser.add_argument("--split", choices=MODES, default="template")
    parser.add_argument("--groups", nargs="+", choices=FEATURE_GROUPS, default=list(FEATURE_GROUPS))
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--reports-dir", type=Path)
    args = parser.parse_args()
    model_dir = args.model_dir or (Path("models") if args.split == "template" else Path("models/random"))
    reports_dir = args.reports_dir or Path("reports/binary") / args.split
    try:
        train(
            pd.read_csv(args.dataset), pd.read_csv(args.splits),
            args.split, args.groups, model_dir, reports_dir,
        )
    except ValueError as error:
        parser.exit(1, f"Ошибка обучения: {error}\n")


if __name__ == "__main__":
    main()

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.features.columns import get_feature_columns


DATASET_PATH = Path("data/processed/query_dataset.csv")
MODEL_PATH = Path("models/query_classifier.joblib")
SCALER_PATH = Path("models/scaler.joblib")
FEATURES_PATH = Path("models/feature_columns.json")

REPORTS_DIR = Path("reports")
METRICS_PATH = REPORTS_DIR / "metrics.json"
FEATURE_IMPORTANCE_PATH = REPORTS_DIR / "feature_importance.csv"


def save_metrics(y_test, y_pred, y_proba, df: pd.DataFrame):
    report = classification_report(
        y_test,
        y_pred,
        output_dict=True,
        zero_division=0,
    )

    metrics = {
        "dataset_rows": int(len(df)),
        "label_distribution": {
            str(label): int(count)
            for label, count in df["label"].value_counts().sort_index().items()
        },
        "accuracy": accuracy_score(y_test, y_pred),
        "roc_auc": roc_auc_score(y_test, y_proba),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "classification_report": report,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    with METRICS_PATH.open("w", encoding="utf-8") as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)

    print(f"Saved metrics: {METRICS_PATH}")


def save_feature_importance(coefficients: pd.DataFrame):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    coefficients.to_csv(FEATURE_IMPORTANCE_PATH, index=False)

    print(f"Saved feature importance: {FEATURE_IMPORTANCE_PATH}")


def main():
    df = pd.read_csv(DATASET_PATH)

    # Запросы, не уложившиеся в таймаут, не имеют метки
    if "status" in df.columns:
        df = df[df["status"] == "ok"]

    # Фактические метрики выполнения исключаются списком из src/features/columns.py
    feature_columns = get_feature_columns(df.columns)

    X = df[feature_columns]
    y = df["label"].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=42,
        stratify=y,
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = LogisticRegression(
        class_weight="balanced",
        max_iter=1000,
        random_state=42,
    )

    model.fit(X_train_scaled, y_train)

    y_pred = model.predict(X_test_scaled)
    y_proba = model.predict_proba(X_test_scaled)[:, 1]

    print("Accuracy:", accuracy_score(y_test, y_pred))
    print("ROC-AUC:", roc_auc_score(y_test, y_proba))

    print("\nConfusion matrix:")
    print(confusion_matrix(y_test, y_pred))

    print("\nClassification report:")
    print(classification_report(y_test, y_pred, zero_division=0))

    coefficients = pd.DataFrame(
        {
            "feature": feature_columns,
            "coefficient": model.coef_[0],
            "abs_coefficient": abs(model.coef_[0]),
        }
    ).sort_values("abs_coefficient", ascending=False)

    print("\nTop feature coefficients:")
    print(coefficients.head(15))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)

    with FEATURES_PATH.open("w", encoding="utf-8") as file:
        json.dump(feature_columns, file, ensure_ascii=False, indent=2)

    save_metrics(y_test, y_pred, y_proba, df)
    save_feature_importance(coefficients)

    print(f"\nSaved model: {MODEL_PATH}")
    print(f"Saved scaler: {SCALER_PATH}")
    print(f"Saved features: {FEATURES_PATH}")


if __name__ == "__main__":
    main()
import argparse
import json
import os
from pathlib import Path

import joblib
import pandas as pd
import psycopg
from dotenv import load_dotenv

import sqlparse
from sqlparse.tokens import DDL, DML, Keyword

from src.features.extract_features import (
    extract_plan_features,
    extract_sql_features,
    normalize_sql,
)


MODEL_PATH = Path("models/query_classifier.joblib")
SCALER_PATH = Path("models/scaler.joblib")
FEATURES_PATH = Path("models/feature_columns.json")

FORBIDDEN_SQL_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "copy",
    "call",
    "execute",
    "vacuum",
    "analyze",
    "lock",
    "commit",
    "rollback",
    "begin",
    "start",
    "into",
}


def get_meaningful_statements(sql: str):
    statements = []

    for statement in sqlparse.parse(sql):
        cleaned = statement.value.strip().strip(";").strip()

        if cleaned:
            statements.append(statement)

    return statements


def get_first_meaningful_token(statement):
    for token in statement.flatten():
        value = token.value.strip()

        if value:
            return token

    return None


def validate_sql(sql: str):
    statements = get_meaningful_statements(sql)

    if len(statements) != 1:
        raise ValueError("Разрешён только один SQL-запрос")

    statement = statements[0]
    first_token = get_first_meaningful_token(statement)

    if first_token is None:
        raise ValueError("SQL-запрос пустой")

    first_value = first_token.value.lower()

    if first_value not in {"select", "with"}:
        raise ValueError("Разрешены только SELECT-запросы")

    for token in statement.flatten():
        value = token.value.strip().lower()

        if not value:
            continue

        if value in FORBIDDEN_SQL_KEYWORDS and (
            token.ttype in DDL
            or token.ttype in DML
            or token.ttype in Keyword
        ):
            raise ValueError(f"Запрещённое ключевое слово: {value}")

def get_connection():
    load_dotenv()

    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def load_feature_columns():
    with FEATURES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_model_objects():
    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    feature_columns = load_feature_columns()

    return model, scaler, feature_columns


def run_explain(cursor, sql: str):
    cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}")
    return cursor.fetchone()[0]


def build_feature_row(sql: str, explain_json: list, feature_columns: list):
    sql_features = extract_sql_features(sql)
    plan_features = extract_plan_features(explain_json)

    features = {
        **sql_features,
        **plan_features,
    }

    row = {
        column: features.get(column, 0)
        for column in feature_columns
    }

    return pd.DataFrame([row])


def get_top_contributions(model, scaled_row, feature_columns, top_n: int = 5):
    coefficients = model.coef_[0]
    values = scaled_row[0]

    contributions = []

    for feature, coefficient, value in zip(feature_columns, coefficients, values):
        contributions.append(
            {
                "feature": feature,
                "contribution": coefficient * value,
            }
        )

    contributions = sorted(
        contributions,
        key=lambda item: abs(item["contribution"]),
        reverse=True,
    )

    return contributions[:top_n]

def predict(sql: str):
    validate_sql(sql)
    sql = normalize_sql(sql)

    model, scaler, feature_columns = load_model_objects()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            explain_json = run_explain(cursor, sql)

    feature_row = build_feature_row(sql, explain_json, feature_columns)
    scaled_row = scaler.transform(feature_row)

    probability_heavy = model.predict_proba(scaled_row)[0][1]
    predicted_label = int(model.predict(scaled_row)[0])

    predicted_class = "heavy" if predicted_label == 1 else "light"

    top_contributions = get_top_contributions(
        model=model,
        scaled_row=scaled_row,
        feature_columns=feature_columns,
    )

    return {
        "class": predicted_class,
        "probability_heavy": probability_heavy,
        "top_contributions": top_contributions,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql", type=str, help="SQL-запрос для классификации")
    parser.add_argument("--file", type=Path, help="Файл с SQL-запросом")
    args = parser.parse_args()

    if args.sql is None and args.file is None:
        raise ValueError("Нужно передать --sql или --file")

    if args.file is not None:
        sql = args.file.read_text(encoding="utf-8")
    else:
        sql = args.sql

    result = predict(sql)

    print("Prediction result")
    print("-----------------")
    print(f"Class: {result['class']}")
    print(f"Probability heavy: {result['probability_heavy']:.4f}")

    print("\nTop feature contributions:")
    for item in result["top_contributions"]:
        print(f"{item['feature']}: {item['contribution']:.4f}")


if __name__ == "__main__":
    main()

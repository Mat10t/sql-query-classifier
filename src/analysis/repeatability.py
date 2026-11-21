"""
Анализ разброса повторных запусков (этап 1).

Ожидает measurements.csv, собранный без прогрева и с нечётным числом запусков:

    python -m src.db.collect_dataset --warmup-runs 0 --runs 15 --limit-per-template 1 ...

Запуск 0 считается первым (без прогрева). Остальные делятся на два блока:
блок оценки (запуски 1..m) и независимый эталонный блок (запуски m+1..2m).
Для каждого k = 1..m сравнивается медиана первых k запусков блока оценки
с медианой эталонного блока. Так видно, сколько повторов достаточно
и насколько искажает результат отсутствие прогрева.
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_MEASUREMENTS_PATH = Path("data/processed/repeatability/measurements.csv")
DEFAULT_DATASET_PATH = Path("data/processed/repeatability/query_dataset.csv")
DEFAULT_OUTPUT_DIR = Path("reports/stage1")

TIME_BINS = [0, 1, 10, 100, 1000, float("inf")]
TIME_BIN_LABELS = ["<1 мс", "1–10 мс", "10–100 мс", "0.1–1 с", ">1 с"]


def analyze_query(times: np.ndarray, block_size: int) -> dict:
    first = times[0]
    estimate_block = times[1:1 + block_size]
    reference_block = times[1 + block_size:1 + 2 * block_size]
    reference = float(np.median(reference_block))

    result = {
        "first_run_ms": float(first),
        "reference_median_ms": reference,
        "first_run_ratio": float(first / reference) if reference > 0 else np.nan,
        "cv": float(np.std(times[1:], ddof=1) / np.mean(times[1:])),
    }

    for k in range(1, block_size + 1):
        # С прогревом: первый запуск отброшен
        warm = np.median(estimate_block[:k])
        # Без прогрева: первый запуск входит в оценку
        cold = np.median(np.concatenate([[first], estimate_block[:k - 1]]))

        result[f"err_warm_k{k}"] = abs(warm - reference) / reference
        result[f"err_cold_k{k}"] = abs(cold - reference) / reference

    return result


def build_convergence(per_query: pd.DataFrame, block_size: int) -> pd.DataFrame:
    rows = []

    for k in range(1, block_size + 1):
        for mode in ["warm", "cold"]:
            errors = per_query[f"err_{mode}_k{k}"]
            rows.append(
                {
                    "k": k,
                    "mode": "с прогревом" if mode == "warm" else "без прогрева",
                    "median_rel_error": errors.median(),
                    "p90_rel_error": errors.quantile(0.9),
                    "share_within_10pct": (errors <= 0.10).mean(),
                }
            )

    return pd.DataFrame(rows)


def plot_convergence(convergence: pd.DataFrame, path: Path):
    figure, axis = plt.subplots(figsize=(7, 4))

    for mode, group in convergence.groupby("mode"):
        axis.plot(group["k"], group["p90_rel_error"] * 100, marker="o", label=f"p90, {mode}")
        axis.plot(
            group["k"], group["median_rel_error"] * 100,
            marker=".", linestyle="--", label=f"медиана, {mode}",
        )

    axis.set_xlabel("Число измеренных запусков k")
    axis.set_ylabel("Отн. ошибка медианы, %")
    axis.set_title("Сходимость оценки t(q) к эталонной медиане")
    axis.grid(alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--measurements", type=Path, default=DEFAULT_MEASUREMENTS_PATH)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    measurements = pd.read_csv(args.measurements)
    dataset = pd.read_csv(args.dataset) if args.dataset.exists() else None
    if dataset is not None and "status" in dataset:
        dataset = dataset.loc[dataset["status"].eq("ok")]
        measurements = measurements[measurements["query_id"].isin(dataset["query_id"])]
    runs_per_query = measurements.groupby("query_id").size()
    if runs_per_query.nunique() != 1:
        raise ValueError("Для анализа нужны полные серии одинаковой длины")
    total_runs = int(runs_per_query.min())

    if total_runs < 5 or total_runs % 2 == 0:
        raise ValueError("Нужно нечётное число запусков (>= 5) без прогрева")

    block_size = (total_runs - 1) // 2

    rows = []

    for query_id, group in measurements.groupby("query_id"):
        times = group.sort_values("run_index")["execution_time_ms"].to_numpy()[:total_runs]
        rows.append({"query_id": query_id, **analyze_query(times, block_size)})

    per_query = pd.DataFrame(rows)

    if dataset is not None:
        per_query = dataset[["query_id", "template_id"]].merge(per_query, on="query_id")

    per_query["time_bin"] = pd.cut(
        per_query["reference_median_ms"], TIME_BINS, labels=TIME_BIN_LABELS, right=False
    )

    convergence = build_convergence(per_query, block_size)

    by_bin = per_query.groupby("time_bin", observed=True).agg(
        queries=("query_id", "count"),
        cv_median=("cv", "median"),
        cv_max=("cv", "max"),
        first_run_ratio_median=("first_run_ratio", "median"),
        first_run_ratio_max=("first_run_ratio", "max"),
    ).reset_index()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    per_query.to_csv(args.output_dir / "repeatability_per_query.csv", index=False)
    convergence.to_csv(args.output_dir / "repeatability_convergence.csv", index=False)
    by_bin.to_csv(args.output_dir / "repeatability_by_time_bin.csv", index=False)
    plot_convergence(convergence, args.output_dir / "repeatability_convergence.png")

    summary = {
        "queries": int(len(per_query)),
        "runs_per_query": total_runs,
        "block_size": block_size,
        "cv_median": float(per_query["cv"].median()),
        "cv_p90": float(per_query["cv"].quantile(0.9)),
        "first_run_ratio_median": float(per_query["first_run_ratio"].median()),
        "first_run_ratio_p90": float(per_query["first_run_ratio"].quantile(0.9)),
        "share_first_run_slower_20pct": float((per_query["first_run_ratio"] > 1.2).mean()),
    }

    with (args.output_dir / "repeatability_summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nСходимость:")
    print(convergence.to_string(index=False))
    print("\nПо диапазонам времени:")
    print(by_bin.to_string(index=False))


if __name__ == "__main__":
    main()

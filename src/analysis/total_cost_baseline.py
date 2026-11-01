"""
Baseline PostgreSQL Total Cost (этап 2).

Total Cost измеряется в условных единицах оптимизатора, поэтому напрямую
сравнивать его с миллисекундами (MAE/RMSE) нельзя. На этом этапе оценивается
только качество ранжирования: насколько порядок запросов по Total Cost
совпадает с порядком по фактическому времени t(q).
Линейная калибровка Total Cost -> мс — отдельный baseline этапа 5.
"""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.evaluation.ranking import ranking_metrics


DEFAULT_DATASET_PATH = Path("data/processed/query_dataset.csv")
DEFAULT_OUTPUT_DIR = Path("reports/stage2")

TARGET = "execution_time_ms"

# Готовые оценки оптимизатора, которые сравниваются как одиночные предикторы
OPTIMIZER_ESTIMATES = ["total_cost", "startup_cost", "plan_rows"]

MIN_QUERIES_PER_TEMPLATE = 3

# Запросы короче 1 мс тривиально отделяются от тяжёлых и завышают общие метрики,
# поэтому ранжирование отдельно считается только среди запросов не короче порога
HEAVY_THRESHOLD_MS = 1.0


def evaluate_estimates(dataset: pd.DataFrame) -> dict:
    return {
        column: ranking_metrics(dataset[column], dataset[TARGET])
        for column in OPTIMIZER_ESTIMATES
    }


def evaluate_by_template(dataset: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for template_id, group in dataset.groupby("template_id"):
        ms_per_cost = group[TARGET] / group["total_cost"]
        row = {
            "template_id": template_id,
            "source": group["source"].iloc[0],
            "queries": len(group),
            "time_median_ms": group[TARGET].median(),
            "total_cost_median": group["total_cost"].median(),
            "ms_per_cost_unit": ms_per_cost.median(),
            "time_max_to_min": group[TARGET].max() / group[TARGET].min(),
            "total_cost_constant": bool(group["total_cost"].nunique() == 1),
        }

        # Внутри шаблона ранжирование имеет смысл, только если различаются
        # и время, и Total Cost (иначе корреляция не определена)
        if (
            len(group) >= MIN_QUERIES_PER_TEMPLATE
            and group[TARGET].nunique() > 1
            and not row["total_cost_constant"]
        ):
            metrics = ranking_metrics(group["total_cost"], group[TARGET])
            row["spearman_within"] = metrics["spearman"]
            row["pairwise_accuracy_within"] = metrics["pairwise_accuracy"]

        rows.append(row)

    return pd.DataFrame(rows).sort_values("time_median_ms")


def plot_cost_vs_time(dataset: pd.DataFrame, path: Path):
    figure, axis = plt.subplots(figsize=(7, 5))

    for source, group in dataset.groupby("source"):
        axis.scatter(group["total_cost"], group[TARGET], s=14, alpha=0.7, label=source)

    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("PostgreSQL Total Cost (усл. ед.)")
    axis.set_ylabel("t(q), медиана Execution Time, мс")
    axis.set_title("Total Cost и фактическое время выполнения")
    axis.grid(alpha=0.3, which="both")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    dataset = pd.read_csv(args.dataset)
    dataset = dataset[dataset["status"] == "ok"]

    by_template = evaluate_by_template(dataset)
    within = by_template.dropna(subset=["spearman_within"])
    heavy = dataset[dataset[TARGET] >= HEAVY_THRESHOLD_MS]

    result = {
        "queries": int(len(dataset)),
        "templates": int(dataset["template_id"].nunique()),
        "overall": evaluate_estimates(dataset),
        f"time_at_least_{HEAVY_THRESHOLD_MS:g}_ms": evaluate_estimates(heavy),
        "by_source": {
            source: ranking_metrics(group["total_cost"], group[TARGET])
            for source, group in dataset.groupby("source")
        },
        "within_template": {
            # Шаблоны, у которых Total Cost одинаков для всех параметров
            "templates_with_constant_cost": int(by_template["total_cost_constant"].sum()),
            "templates_evaluated": int(len(within)),
            "spearman_median": float(within["spearman_within"].median()),
            "pairwise_accuracy_median": float(within["pairwise_accuracy_within"].median()),
        },
        # Разброс «цены» единицы стоимости между шаблонами:
        # если бы Total Cost был откалиброван, отношение было бы близко к константе
        "ms_per_cost_unit_spread": {
            "min": float(by_template["ms_per_cost_unit"].min()),
            "median": float(by_template["ms_per_cost_unit"].median()),
            "max": float(by_template["ms_per_cost_unit"].max()),
            "max_to_min_ratio": float(
                by_template["ms_per_cost_unit"].max() / by_template["ms_per_cost_unit"].min()
            ),
        },
        "log_log_pearson": float(
            np.corrcoef(np.log(dataset["total_cost"]), np.log(dataset[TARGET]))[0, 1]
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with (args.output_dir / "total_cost_baseline.json").open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    by_template.to_csv(args.output_dir / "total_cost_by_template.csv", index=False)
    plot_cost_vs_time(dataset, args.output_dir / "total_cost_vs_time.png")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\nПо шаблонам:")
    print(by_template.to_string(index=False))


if __name__ == "__main__":
    main()

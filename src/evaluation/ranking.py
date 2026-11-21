"""
Метрики качества ранжирования оценки стоимости ĉ относительно фактической c.
Используются для baseline Total Cost и всех последующих моделей.
"""

import numpy as np
from scipy import stats


def pairwise_ordering_accuracy(predicted, actual) -> float:
    """
    Доля пар (i, j) с c_i != c_j, для которых sign(ĉi - ĉj) = sign(ci - cj).
    Пары с равной оценкой ĉ засчитываются как 0.5 (угадывание).
    """
    score = pairwise_summary(predicted, actual)["accuracy"]
    return float("nan") if score is None else score


def pairwise_summary(predicted, actual, bounds=None):
    """Число сравнимых пар и доля верных порядков. Касание диапазонов считается пересечением."""
    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)
    i, j = np.triu_indices(len(actual), k=1)
    actual_sign = np.sign(actual[i] - actual[j])
    comparable = actual_sign != 0
    if bounds is not None:
        lower, upper = (np.asarray(values, dtype=float) for values in bounds)
        comparable &= (upper[i] < lower[j]) | (upper[j] < lower[i])
    actual_sign = actual_sign[comparable]
    predicted_sign = np.sign(predicted[i[comparable]] - predicted[j[comparable]])
    count = len(actual_sign)
    correct = int(np.sum(predicted_sign == actual_sign))
    tied = int(np.sum(predicted_sign == 0))
    return {
        "pairs": count,
        "correct": correct,
        "tied_prediction": tied,
        "accuracy": (correct + 0.5 * tied) / count if count else None,
    }


def ranking_metrics(predicted, actual, *, include_pair_count=False) -> dict:
    spearman = stats.spearmanr(predicted, actual)
    kendall = stats.kendalltau(predicted, actual)

    pairs = pairwise_summary(predicted, actual)
    metrics = {
        "n": int(len(actual)),
        "spearman": float(spearman.statistic),
        "kendall_tau": float(kendall.statistic),
        "pairwise_accuracy": pairs["accuracy"] if pairs["pairs"] else float("nan"),
    }
    if include_pair_count:
        metrics["distinct_time_pairs"] = pairs["pairs"]
    return metrics

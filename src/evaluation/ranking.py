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
    predicted = np.asarray(predicted, dtype=float)
    actual = np.asarray(actual, dtype=float)

    i, j = np.triu_indices(len(actual), k=1)
    actual_sign = np.sign(actual[i] - actual[j])
    predicted_sign = np.sign(predicted[i] - predicted[j])

    comparable = actual_sign != 0

    if not comparable.any():
        return float("nan")

    actual_sign = actual_sign[comparable]
    predicted_sign = predicted_sign[comparable]

    score = (predicted_sign == actual_sign).astype(float)
    score[predicted_sign == 0] = 0.5

    return float(score.mean())


def ranking_metrics(predicted, actual) -> dict:
    spearman = stats.spearmanr(predicted, actual)
    kendall = stats.kendalltau(predicted, actual)

    return {
        "n": int(len(actual)),
        "spearman": float(spearman.statistic),
        "kendall_tau": float(kendall.statistic),
        "pairwise_accuracy": pairwise_ordering_accuracy(predicted, actual),
    }

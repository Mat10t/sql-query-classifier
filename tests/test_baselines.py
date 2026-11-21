import unittest

import numpy as np
import pandas as pd

from src.evaluation.baselines import run
from src.evaluation.ranking import pairwise_ordering_accuracy, pairwise_summary
from src.features.columns import FEATURE_GROUPS


class BaselineTest(unittest.TestCase):
    def test_rank_pairs_respect_touching_intervals_and_ties(self):
        times = [1, 2, 3, 3]
        scores = [1, 1, 1, 2]
        self.assertEqual(pairwise_ordering_accuracy(scores, times), 0.7)
        pairs = pairwise_summary(scores, times, bounds=([0, 1.5, 2.5, 3], [1.5, 2.5, 3, 4]))
        self.assertEqual(pairs, {"pairs": 3, "correct": 2, "tied_prediction": 1, "accuracy": 2.5 / 3})
        self.assertIsNone(pairwise_summary([1, 2], [1, 2], bounds=([0, 0], [3, 3]))["accuracy"])

    def test_raw_cost_log_target_and_held_out_times(self):
        costs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        data = pd.DataFrame({
            "query_id": list("abcde"), "template_id": list("ABCDE"),
            "execution_time_ms": np.expm1(0.25 + 0.2 * costs),
        })
        for names in FEATURE_GROUPS.values():
            for name in names:
                data[name] = 0
        data["total_cost"] = costs
        manifest = data[["query_id", "template_id"]].assign(
            template=["train", "train", "train", "test", "test"],
            random=["test", "train", "train", "train", "test"],
        )
        data.loc[3:, "execution_time_ms"] += 7
        data["exec_time_min_ms"] = data["exec_time_max_ms"] = data["execution_time_ms"]
        metrics, predictions = run(data.sample(frac=1, random_state=7), manifest)
        result = metrics["template"]["regression"]
        self.assertAlmostEqual(result["coefficient"], 0.2)
        self.assertAlmostEqual(result["intercept"], 0.25)
        self.assertAlmostEqual(result["errors_ms"]["mae"], 7.0)
        self.assertAlmostEqual(result["errors_ms"]["rmse"], 7.0)
        self.assertEqual(list(predictions.loc[predictions.split == "template", "query_id"]), list("de"))
        self.assertEqual(list(predictions.loc[predictions.split == "random", "query_id"]), list("ae"))

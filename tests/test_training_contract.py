import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.evaluation.splits import build_splits, validate_splits
from src.features.columns import FEATURE_GROUPS, get_feature_columns
from src.model.train_model import binary_labels, train


class TrainingContractTest(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame({
            "query_id": [f"q{i}" for i in range(24)],
            "template_id": [f"t{i // 3}" for i in range(24)],
            "execution_time_ms": list(range(1, 25)),
            "label": [0] * 24,
        })
        for names in FEATURE_GROUPS.values():
            for name in names:
                self.data[name] = 1
        self.splits = build_splits(self.data)

    def test_allowlist_and_groups(self):
        self.assertEqual(len(get_feature_columns(self.data.columns)), 22)
        self.assertEqual(get_feature_columns(self.data.columns, ["structure"]), ["node_count"])
        with self.assertRaisesRegex(ValueError, "total_cost"):
            get_feature_columns(self.data.drop(columns="total_cost").columns, ["sql"])

    def test_training_rejects_unknown_column_before_writing(self):
        data = self.data.assign(actual_rows=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaisesRegex(ValueError, "actual_rows"):
                train(data, self.splits, "template", ["sql"], path, path)
            self.assertEqual(list(path.iterdir()), [])

    def test_group_split_is_stable_and_disjoint(self):
        shuffled = self.data.sample(frac=1, random_state=9)
        pd.testing.assert_frame_equal(build_splits(shuffled), self.splits)
        pd.testing.assert_frame_equal(validate_splits(shuffled, self.splits), self.splits)
        self.assertTrue(self.splits.groupby("template_id")["template"].nunique().eq(1).all())
        self.assertEqual(set(self.splits["random"]), {"train", "test"})

    def test_mixed_template_is_rejected(self):
        other = self.splits.copy()
        other.loc[0, "template"] = "train" if other.loc[0, "template"] == "test" else "test"
        with self.assertRaisesRegex(ValueError, "одновременно"):
            validate_splits(self.data, other)

    def test_changed_corpus_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Состав"):
            validate_splits(self.data.iloc[1:], self.splits)

    def test_threshold_uses_train_only_and_strict_boundary(self):
        train_time = pd.Series([1, 2, 3, 4, 5])
        first = binary_labels(train_time, pd.Series([4, 5]))
        other = binary_labels(train_time, pd.Series([4000, 5000]))
        self.assertEqual(first[0], 4)
        self.assertEqual(other[0], first[0])
        self.assertEqual(first[1].tolist(), [0, 0, 0, 0, 1])
        self.assertEqual(first[2].tolist(), [0, 1])
        self.assertEqual(other[2].tolist(), [1, 1])



    def test_training_ignores_csv_labels_and_test_times_for_threshold(self):
        data = self.data.copy()
        mask = data["query_id"].isin(self.splits.loc[self.splits["template"] == "train", "query_id"])
        expected = data.loc[mask, "execution_time_ms"].quantile(0.75)
        data.loc[~mask, "execution_time_ms"] = 100_000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            train(data, self.splits, "template", ["structure"], path, path)
            metrics = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["threshold_ms"], expected)
            self.assertEqual(metrics["confusion_matrix"][0], [0, 0])
            self.assertIsNone(metrics["roc_auc"])
            self.assertEqual(json.loads((path / "feature_columns.json").read_text()), ["node_count"])

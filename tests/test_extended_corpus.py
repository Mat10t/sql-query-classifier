import unittest

import pandas as pd

from src.analysis.extended_corpus import coverage
from src.db.build_extended_workload import build_version
from src.evaluation.splits import build_splits


class ExtendedCorpusTest(unittest.TestCase):
    def test_frozen_assignments_and_unique_queries(self):
        base = [{"id": f"q{i}", "template_id": f"gen_{i // 2}", "sql": f"SELECT {i};"}
                for i in range(16)]
        keys = pd.DataFrame([(q["id"], q["template_id"]) for q in base],
                            columns=["query_id", "template_id"])
        old = build_splits(keys)
        queries, split = build_version(base, old)
        retained = split.loc[split.query_id.isin(old.query_id)].reset_index(drop=True)
        pd.testing.assert_frame_equal(old, retained)
        self.assertEqual(len({q["sql"] for q in queries}), len(base) + 96)
        self.assertEqual(split.groupby("template_id").template.nunique().max(), 1)
        self.assertEqual(queries, build_version(base, old)[0])

    def test_measurement_bin_boundaries(self):
        rows = pd.DataFrame({"execution_time_ms": [0, 1, 9, 10, 99, 100],
                             "template_id": list("aaabcc")})
        result = coverage(rows)
        self.assertEqual(result["1_to_10_ms"], 2)
        self.assertEqual(result["10_to_100_ms"], 2)
        self.assertEqual(result["1_to_100_ms"], 4)
        self.assertEqual(result["templates_in_1_to_100_ms"], 3)

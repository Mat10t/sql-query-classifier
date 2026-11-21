import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from psycopg.errors import QueryCanceled

from src.checks import check_leakage
from src.checks.check_collection import validate_collection
from src.db import collect_dataset
from src.measure.protocol import extract_execution_metrics


PLAN = [{"Plan": {"Node Type": "Result", "Total Cost": 1}}]


def analyze(time):
    return [{"Plan": PLAN[0]["Plan"], "Execution Time": time}]


class MeasurementJournalTest(unittest.TestCase):
    def collect(self, outcomes, warmups=1, measured=3):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        queries = [{"id": key, "sql": "SELECT 1"} for key in outcomes]
        (root / "queries.json").write_text(json.dumps(queries), encoding="utf-8")
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        # Команды SET ничего не читают. Каждому EXPLAIN соответствует один ответ.
        replies = iter(item for sequence in outcomes.values() for item in sequence)

        def execute(sql):
            if sql.startswith("SET"):
                return
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            cursor.fetchone.return_value = (reply,)

        cursor.execute.side_effect = execute
        args = [
            "collect", "--queries", str(root / "queries.json"), "--output", str(root / "data.csv"),
            "--measurements-output", str(root / "runs.csv"), "--plans-output", str(root / "plans.jsonl"),
            "--warmup-runs", str(warmups), "--runs", str(measured), "--label-quantile", "0.75",
        ]
        with patch.object(collect_dataset, "get_connection", return_value=connection), patch.object(sys, "argv", args):
            with redirect_stdout(StringIO()):
                collect_dataset.main()
        data = pd.read_csv(root / "data.csv")
        runs = pd.read_csv(root / "runs.csv")
        plans = [json.loads(s) for s in (root / "plans.jsonl").read_text(encoding="utf-8").splitlines()]
        validate_collection(list(outcomes), data, runs, [p["query_id"] for p in plans], warmups, measured)
        return data, runs, plans, root

    def test_early_error_timeout_and_success_in_one_collection(self):
        outcomes = {
            "bad": [ValueError("ошибка плана")],
            "partial": [PLAN, analyze(10), analyze(2), QueryCanceled("statement timeout")],
            "good": [PLAN, analyze(100), analyze(3), analyze(4), analyze(2)],
        }
        data, runs, plans, folder = self.collect(outcomes)
        rows = data.set_index("query_id")
        self.assertEqual(data["status"].tolist(), ["error", "timeout", "ok"])
        self.assertIn("ошибка плана", rows.at["bad", "error"])
        self.assertIn("запуск 2", rows.at["partial", "error"])
        self.assertTrue(rows.loc[["bad", "partial"], ["execution_time_ms", "label"]].isna().all().all())
        self.assertEqual(rows["measured_runs"].tolist(), [0, 1, 3])
        self.assertEqual(runs.loc[runs["query_id"] == "partial", "execution_time_ms"].tolist(), [10, 2])
        self.assertIsNone(plans[0]["explain"])
        self.assertEqual(plans[1]["explain_analyze"], analyze(2))
        self.assertEqual(rows.at["good", "execution_time_ms"], 3)
        self.assertTrue(pd.isna(rows.at["good", "planning_time_ms"]))
        with patch.object(sys, "argv", ["check", "--dataset", str(folder / "data.csv"),
                                       "--plans", str(folder / "plans.jsonl")]):
            with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as exit_code:
                check_leakage.main()
        self.assertEqual(exit_code.exception.code, 0)

    def test_missing_execution_time_preserves_only_completed_runs(self):
        data, runs, _, _ = self.collect({"bad": [PLAN, analyze(7), PLAN]})
        self.assertEqual(runs["execution_time_ms"].tolist(), [7])
        self.assertEqual(data.at[0, "status"], "error")
        self.assertIn("Execution Time", data.at[0, "error"])
        self.assertTrue(pd.isna(data.at[0, "execution_time_ms"]))

    def test_no_completed_runs_produces_readable_csv(self):
        data, runs, _, _ = self.collect({"bad": [QueryCanceled("statement timeout")]})
        self.assertEqual(data.at[0, "status"], "timeout")
        self.assertTrue(runs.empty)
        self.assertIn("run_index", runs.columns)

    def test_invalid_time_and_genuine_zero(self):
        for time in [None, "1", True, -1, float("nan"), float("inf")]:
            with self.subTest(time=time), self.assertRaisesRegex(ValueError, "Execution Time"):
                extract_execution_metrics(analyze(time))
        self.assertEqual(extract_execution_metrics(analyze(0))["execution_time_ms"], 0)

    def test_detects_lost_row_duplicate_and_missing_run(self):
        keys = ["a", "b"]
        data, runs, _, _ = self.collect({key: [PLAN, analyze(1)] for key in keys}, warmups=0, measured=1)
        for invalid in [data.iloc[:1], pd.concat([data, data.iloc[:1]])]:
            with self.assertRaisesRegex(ValueError, "Результаты"):
                validate_collection(keys, invalid, runs, keys, 0, 1)
        with self.assertRaisesRegex(ValueError, "measured_runs"):
            validate_collection(keys, data, runs.iloc[:1], keys, 0, 1)

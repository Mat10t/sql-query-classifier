import sqlite3
import unittest

from src.db.snapshot_environment import get_statistics_fingerprint


class StatisticsFingerprintTest(unittest.TestCase):
    def setUp(self):
        # Небольшая локальная таблица воспроизводит нужные столбцы pg_stats.
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("""
            CREATE TABLE pg_stats (
                schemaname TEXT, tablename TEXT, attname TEXT, inherited BOOLEAN,
                null_frac REAL, avg_width INTEGER, n_distinct REAL, most_common_vals TEXT,
                most_common_freqs TEXT, histogram_bounds TEXT, correlation REAL
            )
        """)
        self.db.execute("""
            INSERT INTO pg_stats VALUES
                ('public', 'orders', 'priority', FALSE, 0, 4, 5, '{1}', '{0.25}', NULL, 0.4)
        """)

    def snapshot(self):
        return get_statistics_fingerprint(self.db.cursor())

    def test_repeatable_and_self_describing(self):
        # Порядок выдачи строк без сортировки может измениться между запросами.
        self.db.execute("INSERT INTO pg_stats SELECT * FROM pg_stats")
        self.db.execute("UPDATE pg_stats SET inherited = TRUE WHERE rowid = 2")
        self.db.execute("CREATE TEMP TABLE saved AS SELECT * FROM pg_stats")
        before = self.snapshot()
        self.db.execute("DELETE FROM pg_stats")
        self.db.execute("INSERT INTO pg_stats SELECT * FROM saved ORDER BY rowid DESC")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(before["fingerprint_version"], 2)
        self.assertEqual(before["schema"], "public")
        self.assertEqual(before["columns_with_stats"], 2)
        self.assertEqual(before["fields"], [
            "tablename", "attname", "inherited", "null_frac", "avg_width",
            "n_distinct", "most_common_vals", "most_common_freqs",
            "histogram_bounds", "correlation",
        ])

    def test_change_of_frequencies(self):
        before = self.snapshot()
        self.db.execute("UPDATE pg_stats SET most_common_freqs = '{0.5}'")
        self.assertNotEqual(before["sha256"], self.snapshot()["sha256"])

    def test_change_of_correlation(self):
        before = self.snapshot()
        self.db.execute("UPDATE pg_stats SET correlation = -0.4")
        self.assertNotEqual(before["sha256"], self.snapshot()["sha256"])

    def test_other_schemas_are_excluded(self):
        before = self.snapshot()
        self.db.execute("""
            INSERT INTO pg_stats VALUES
                ('other', 'orders', 'priority', FALSE, 0, 4, 5, '{1}', '{0.5}', NULL, NULL)
        """)
        self.assertEqual(before, self.snapshot())

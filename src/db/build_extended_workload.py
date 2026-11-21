"""Вторая версия корпуса и фиксированное продолжение разбиений этапа 4."""

import argparse
import json
import random
from pathlib import Path

import pandas as pd

from src.db.workload import load_queries
from src.evaluation.splits import SEED, SPLIT_PATH, build_splits, validate_splits


BASE = Path("data/queries/combined_tpch_queries.json")
CORPUS = Path("data/queries/v2/queries.json")
SPLITS = Path("reports/stage5/v2/splits.csv")

# Начала диапазонов выбраны в двух частях домена ключа TPC-H SF=1.
# Ширина умножается на 1, 2, 4, 8, 16, 32 независимо от измеренного времени.
TEMPLATES = {
    "order_status_totals": ((400000, 3200000), 8192, """
        SELECT o_orderstatus, count(*), sum(o_totalprice) FROM orders
        WHERE o_orderkey >= {lo} AND o_orderkey < {hi}
        GROUP BY o_orderstatus"""),
    "top_parts_by_quantity": ((400000, 3200000), 2048, """
        SELECT l_partkey, sum(l_quantity) AS quantity FROM lineitem
        WHERE l_orderkey >= {lo} AND l_orderkey < {hi}
        GROUP BY l_partkey ORDER BY quantity DESC, l_partkey LIMIT 20"""),
    "customer_urgent_orders": ((12000, 82000), 128, """
        SELECT c_mktsegment, count(*) FROM customer
        WHERE c_custkey >= {lo} AND c_custkey < {hi} AND EXISTS (
          SELECT 1 FROM orders WHERE o_custkey = c_custkey AND o_orderpriority = '1-URGENT')
        GROUP BY c_mktsegment"""),
    "inventory_by_brand": ((14000, 110000), 256, """
        SELECT p_brand, sum(ps_availqty * ps_supplycost) FROM part
        JOIN partsupp ON ps_partkey = p_partkey
        WHERE p_partkey >= {lo} AND p_partkey < {hi} GROUP BY p_brand"""),
    "supplier_ship_modes": ((400, 6200), 4, """
        SELECT l_shipmode, count(*), sum(l_extendedprice) FROM lineitem
        WHERE l_suppkey >= {lo} AND l_suppkey < {hi}
        GROUP BY l_shipmode"""),
    "order_price_changes": ((400000, 3200000), 4096, """
        SELECT avg(abs(price_change)) FROM (
          SELECT o_totalprice - lag(o_totalprice) OVER (
            PARTITION BY o_custkey ORDER BY o_orderdate, o_orderkey) AS price_change
          FROM orders WHERE o_orderkey >= {lo} AND o_orderkey < {hi}) AS changes"""),
    "part_stock_extremes": ((14000, 110000), 512, """
        SELECT ps_partkey, min(ps_supplycost), max(ps_supplycost) FROM partsupp
        WHERE ps_partkey >= {lo} AND ps_partkey < {hi}
        GROUP BY ps_partkey HAVING sum(ps_availqty) > 20000"""),
    "nation_balance": ((12000, 82000), 1024, """
        SELECT n_name, c_mktsegment, avg(c_acctbal) FROM customer
        JOIN nation ON n_nationkey = c_nationkey
        WHERE c_custkey >= {lo} AND c_custkey < {hi}
        GROUP BY n_name, c_mktsegment"""),
}


def build_version(base, old_splits):
    additions = []
    for name, (anchors, unit, sql) in TEMPLATES.items():
        for lo in anchors:
            for scale in (1, 2, 4, 8, 16, 32):
                width = unit * scale
                additions.append({
                    "id": f"v2_{name}_{lo}_{width}",
                    "template_id": f"v2_{name}",
                    "source": "generator",
                    "query_type": name,
                    "expected_complexity": None,
                    "sql": " ".join(sql.format(lo=lo, hi=lo + width).split()) + ";",
                })
    def keys(queries):
        return pd.DataFrame([(q["id"], q["template_id"]) for q in queries],
                            columns=["query_id", "template_id"])

    validate_splits(keys(base), old_splits)
    queries = [*base, *additions]
    texts = {" ".join(q["sql"].lower().split()) for q in queries}
    if len(texts) != len(queries):
        raise ValueError("В корпусе повторяется текст SQL")
    manifest = pd.concat([old_splits, build_splits(keys(additions))], ignore_index=True)
    manifest = validate_splits(keys(queries), manifest)
    random.Random(SEED).shuffle(queries)
    return queries, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Сверить сохранённые SQL и назначения")
    args = parser.parse_args()
    queries, manifest = build_version(load_queries(BASE), pd.read_csv(SPLIT_PATH))
    if args.check:
        if queries != load_queries(CORPUS) or not manifest.equals(pd.read_csv(SPLITS)):
            raise ValueError("Версия SQL или назначения отличаются от сохранённых")
    else:
        CORPUS.parent.mkdir(parents=True, exist_ok=True)
        SPLITS.parent.mkdir(parents=True, exist_ok=True)
        CORPUS.write_text(json.dumps(queries, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")
        manifest.to_csv(SPLITS, index=False, lineterminator="\n")
    print(f"Запросов: {len(queries)}, шаблонов: {manifest.template_id.nunique()}")
    print(manifest.groupby("template").agg(queries=("query_id", "size"), templates=("template_id", "nunique")))


if __name__ == "__main__":
    main()

import json
import random
from pathlib import Path


OUTPUT_PATH = Path("data/queries/generated_tpch_queries.json")
RANDOM_SEED = 42


DATES = [
    "1992-01-01",
    "1993-01-01",
    "1994-01-01",
    "1995-01-01",
    "1996-01-01",
    "1997-01-01",
]

SEGMENTS = [
    "AUTOMOBILE",
    "BUILDING",
    "FURNITURE",
    "HOUSEHOLD",
    "MACHINERY",
]

PRIORITIES = [
    "1-URGENT",
    "2-HIGH",
    "3-MEDIUM",
    "4-NOT SPECIFIED",
    "5-LOW",
]

LIMITS = [10, 50, 100, 500, 1000]


def add_query(queries, query_id, query_type, expected_complexity, sql):
    queries.append(
        {
            "id": query_id,
            # Шаблон = тип запроса: экземпляры отличаются только параметрами
            "template_id": f"gen_{query_type}",
            "source": "generator",
            "query_type": query_type,
            "expected_complexity": expected_complexity,
            "sql": sql,
        }
    )


def generate_queries():
    random.seed(RANDOM_SEED)
    queries = []

    query_number = 1

    # Простые запросы по customer
    for custkey in range(1, 51):
        add_query(
            queries,
            f"q{query_number:04d}",
            "simple_lookup",
            "light",
            f"SELECT c_custkey, c_name, c_acctbal FROM customer WHERE c_custkey = {custkey};",
        )
        query_number += 1

    # Фильтрация orders по дате и лимиту
    for date in DATES:
        for limit in LIMITS:
            add_query(
                queries,
                f"q{query_number:04d}",
                "filter_orders",
                "light",
                f"SELECT o_orderkey, o_orderdate, o_totalprice FROM orders "
                f"WHERE o_orderdate >= DATE '{date}' LIMIT {limit};",
            )
            query_number += 1

    # JOIN customer + orders
    for segment in SEGMENTS:
        for limit in LIMITS:
            add_query(
                queries,
                f"q{query_number:04d}",
                "join_customer_orders",
                "medium",
                f"SELECT c.c_name, o.o_orderkey, o.o_totalprice "
                f"FROM customer c "
                f"JOIN orders o ON c.c_custkey = o.o_custkey "
                f"WHERE c.c_mktsegment = '{segment}' "
                f"LIMIT {limit};",
            )
            query_number += 1

    # Агрегация orders
    for date in DATES:
        add_query(
            queries,
            f"q{query_number:04d}",
            "orders_group_by",
            "medium",
            f"SELECT o_orderpriority, COUNT(*) AS orders_count, SUM(o_totalprice) AS total_price "
            f"FROM orders "
            f"WHERE o_orderdate >= DATE '{date}' "
            f"GROUP BY o_orderpriority "
            f"ORDER BY total_price DESC;",
        )
        query_number += 1

    # Агрегация lineitem
    for date in DATES:
        add_query(
            queries,
            f"q{query_number:04d}",
            "lineitem_group_by",
            "medium",
            f"SELECT l_returnflag, l_linestatus, "
            f"SUM(l_quantity) AS sum_qty, "
            f"SUM(l_extendedprice) AS sum_price, "
            f"AVG(l_discount) AS avg_discount "
            f"FROM lineitem "
            f"WHERE l_shipdate >= DATE '{date}' "
            f"GROUP BY l_returnflag, l_linestatus;",
        )
        query_number += 1

    # Тяжёлый JOIN customer + orders + lineitem
    for segment in SEGMENTS:
        for date in DATES:
            add_query(
                queries,
                f"q{query_number:04d}",
                "join_customer_orders_lineitem",
                "heavy",
                f"SELECT c.c_name, COUNT(*) AS items_count, "
                f"SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue "
                f"FROM customer c "
                f"JOIN orders o ON c.c_custkey = o.o_custkey "
                f"JOIN lineitem l ON o.o_orderkey = l.l_orderkey "
                f"WHERE c.c_mktsegment = '{segment}' "
                f"AND o.o_orderdate >= DATE '{date}' "
                f"GROUP BY c.c_name "
                f"ORDER BY revenue DESC "
                f"LIMIT 100;",
            )
            query_number += 1

    # JOIN supplier + partsupp + part
    for size in range(1, 51, 5):
        add_query(
            queries,
            f"q{query_number:04d}",
            "join_supplier_partsupp_part",
            "heavy",
            f"SELECT s.s_name, p.p_brand, COUNT(*) AS cnt, AVG(ps.ps_supplycost) AS avg_cost "
            f"FROM supplier s "
            f"JOIN partsupp ps ON s.s_suppkey = ps.ps_suppkey "
            f"JOIN part p ON ps.ps_partkey = p.p_partkey "
            f"WHERE p.p_size >= {size} "
            f"GROUP BY s.s_name, p.p_brand "
            f"ORDER BY avg_cost DESC "
            f"LIMIT 100;",
        )
        query_number += 1

    # Оконные функции
    for date in DATES:
        add_query(
            queries,
            f"q{query_number:04d}",
            "window_function",
            "heavy",
            f"SELECT o_custkey, o_orderkey, o_totalprice, "
            f"RANK() OVER (PARTITION BY o_custkey ORDER BY o_totalprice DESC) AS price_rank "
            f"FROM orders "
            f"WHERE o_orderdate >= DATE '{date}';",
        )
        query_number += 1

    # Подзапросы
    for threshold in [100000, 250000, 500000, 750000, 1000000]:
        add_query(
            queries,
            f"q{query_number:04d}",
            "subquery",
            "heavy",
            f"SELECT c.c_name, c.c_acctbal "
            f"FROM customer c "
            f"WHERE c.c_custkey IN ("
            f"SELECT o.o_custkey "
            f"FROM orders o "
            f"GROUP BY o.o_custkey "
            f"HAVING SUM(o.o_totalprice) > {threshold}"
            f");",
        )
        query_number += 1

    return queries


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    queries = generate_queries()

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(queries, file, ensure_ascii=False, indent=2)

    print(f"Generated queries: {len(queries)}")
    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

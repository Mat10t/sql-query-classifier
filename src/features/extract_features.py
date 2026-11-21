import re
from collections import Counter

import sqlparse

from src.measure.protocol import extract_execution_metrics


AGGREGATE_FUNCTIONS = [
    "count",
    "sum",
    "avg",
    "min",
    "max",
]


def normalize_sql(sql: str) -> str:
    formatted_sql = sqlparse.format(
        sql,
        keyword_case="lower",
        strip_comments=True,
        strip_whitespace=True,
    )

    return formatted_sql.strip().rstrip(";")


def get_flat_tokens(sql: str) -> list[str]:
    parsed = sqlparse.parse(sql)

    if len(parsed) == 0:
        return []

    tokens = []

    for token in parsed[0].flatten():
        value = token.value.strip().lower()

        if value:
            tokens.append(value)

    return tokens


def extract_sql_features(sql: str) -> dict:
    normalized_sql = normalize_sql(sql)
    tokens = get_flat_tokens(normalized_sql)
    token_text = " ".join(tokens)

    return {
        "query_length": len(normalized_sql),
        "token_count": len(tokens),
        "join_count": tokens.count("join"),
        "where_count": tokens.count("where"),
        "group_by_count": len(re.findall(r"\bgroup\s+by\b", token_text)),
        "order_by_count": len(re.findall(r"\border\s+by\b", token_text)),
        "subquery_count": len(re.findall(r"\(\s*select\b", normalized_sql)),
        "aggregate_func_count": sum(
            1
            for token in tokens
            if token in AGGREGATE_FUNCTIONS
        ),
        "window_func_count": tokens.count("over"),
    }


def walk_plan_nodes(plan: dict):
    yield plan

    for child in plan.get("Plans", []):
        yield from walk_plan_nodes(child)


def extract_plan_features(explain_json: list) -> dict:
    root_plan = explain_json[0]["Plan"]
    nodes = list(walk_plan_nodes(root_plan))

    node_types = Counter(node.get("Node Type", "") for node in nodes)

    return {
        "total_cost": root_plan.get("Total Cost", 0),
        "startup_cost": root_plan.get("Startup Cost", 0),
        "plan_rows": root_plan.get("Plan Rows", 0),
        "plan_width": root_plan.get("Plan Width", 0),
        "node_count": len(nodes),
        "seq_scan_count": node_types.get("Seq Scan", 0),
        "index_scan_count": (
            node_types.get("Index Scan", 0)
            + node_types.get("Index Only Scan", 0)
        ),
        "sort_node_count": node_types.get("Sort", 0),
        "aggregate_node_count": node_types.get("Aggregate", 0),
        "hash_join_count": node_types.get("Hash Join", 0),
        "merge_join_count": node_types.get("Merge Join", 0),
        "nested_loop_count": node_types.get("Nested Loop", 0),
        "window_agg_count": node_types.get("WindowAgg", 0),
    }

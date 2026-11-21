"""
Разделение колонок датасета на служебные, целевые и входные признаки.

Входными признаками могут быть только величины, известные до выполнения
запроса: признаки SQL-текста и признаки плана из EXPLAIN без ANALYZE.
Всё, что получено из EXPLAIN ANALYZE, относится к целевым колонкам.
"""

META_COLUMNS = [
    "query_id",
    "template_id",
    "source",
    "query_type",
    "expected_complexity",
    "sql_text",
    "status",
    "error",
]

# Фактические метрики выполнения и производные от них величины.
# Для нового запроса они заранее неизвестны.
TARGET_COLUMNS = [
    "execution_time_ms",
    "exec_time_min_ms",
    "exec_time_max_ms",
    "exec_time_mean_ms",
    "exec_time_std_ms",
    "exec_time_cv",
    "planning_time_ms",
    "measured_runs",
    "is_unstable",
    "label",
]

NON_FEATURE_COLUMNS = META_COLUMNS + TARGET_COLUMNS


FEATURE_GROUPS = {
    "optimizer": ("total_cost", "startup_cost"),
    "cardinality": ("plan_rows", "plan_width"),
    "structure": ("node_count",),
    "operators": (
        "seq_scan_count", "index_scan_count", "sort_node_count", "aggregate_node_count",
        "hash_join_count", "merge_join_count", "nested_loop_count", "window_agg_count",
    ),
    "sql": (
        "query_length", "token_count", "join_count", "where_count", "group_by_count",
        "order_by_count", "subquery_count", "aggregate_func_count", "window_func_count",
    ),
}


def get_feature_columns(columns, groups=None) -> list[str]:
    known = {feature for features in FEATURE_GROUPS.values() for feature in features}
    present = set(columns)
    unknown = present - known - set(NON_FEATURE_COLUMNS)
    missing = known - present
    if unknown:
        raise ValueError(f"Неизвестные колонки датасета: {sorted(unknown)}")
    if missing:
        raise ValueError(f"Отсутствуют обязательные признаки: {sorted(missing)}")

    selected = list(FEATURE_GROUPS if groups is None else groups)
    if not selected or set(selected) - FEATURE_GROUPS.keys():
        raise ValueError(f"Некорректные группы признаков: {selected}")
    return [
        feature
        for group, features in FEATURE_GROUPS.items() if group in selected
        for feature in features
    ]

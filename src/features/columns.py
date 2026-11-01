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


def get_feature_columns(columns) -> list[str]:
    return [column for column in columns if column not in NON_FEATURE_COLUMNS]

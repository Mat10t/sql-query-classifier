"""
Протокол измерения фактического времени выполнения SQL-запроса.

Целевая величина t(q) — медиана Execution Time по MEASURED_RUNS запускам
EXPLAIN (ANALYZE, TIMING OFF) после WARMUP_RUNS прогревочных запусков
в выбранной конфигурации стенда. Полнота прогрева кэша отдельно не проверялась. Подробное обоснование —
в docs/stage1.md.
"""

import json
import math
import statistics


WARMUP_RUNS = 1
MEASURED_RUNS = 5
STATEMENT_TIMEOUT_MS = 120_000

# Порог коэффициента вариации, выше которого измерение считается нестабильным.
UNSTABLE_CV = 0.2

# Параметры сессии, фиксируемые для всех измерений.
# JIT и параллельные воркеры заметно увеличивают разброс времени,
# поэтому на стенде они отключены.
SESSION_SETTINGS = {
    "jit": "off",
    "max_parallel_workers_per_gather": "0",
    "statement_timeout": str(STATEMENT_TIMEOUT_MS),
}

EXPLAIN_SQL = "EXPLAIN (FORMAT JSON) {sql}"

# TIMING OFF убирает накладные расходы на замер времени каждого узла,
# общий Execution Time при этом сохраняется.
EXPLAIN_ANALYZE_SQL = "EXPLAIN (ANALYZE, TIMING OFF, BUFFERS, FORMAT JSON) {sql}"


def apply_session_settings(cursor, settings: dict = SESSION_SETTINGS):
    for name, value in settings.items():
        cursor.execute(f"SET {name} = '{value}'")


def run_explain(cursor, sql: str) -> list:
    cursor.execute(EXPLAIN_SQL.format(sql=sql))
    return as_json(cursor.fetchone()[0])


def run_explain_analyze(cursor, sql: str) -> list:
    cursor.execute(EXPLAIN_ANALYZE_SQL.format(sql=sql))
    return as_json(cursor.fetchone()[0])


def as_json(value):
    # psycopg обычно сам разбирает json, но на всякий случай поддерживаем строку
    if isinstance(value, str):
        return json.loads(value)

    return value


def extract_execution_metrics(analyze_json: list) -> dict:
    root = analyze_json[0]
    elapsed = root.get("Execution Time")
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("Отсутствует или некорректно обязательное поле Execution Time")
    return {"execution_time_ms": elapsed, "planning_time_ms": root.get("Planning Time")}


def iter_query_runs(cursor, sql: str, warmup_runs: int, measured_runs: int):
    if warmup_runs < 0 or measured_runs < 1:
        raise ValueError("Требуется хотя бы один измеренный запуск и неотрицательное число прогревов")
    for run_index in range(warmup_runs + measured_runs):
        plan = run_explain_analyze(cursor, sql)
        yield {
            "run_index": run_index,
            "is_warmup": run_index < warmup_runs,
            **extract_execution_metrics(plan),
        }, plan


def measure_query(cursor, sql: str, warmup_runs: int, measured_runs: int) -> dict:
    """Возвращает полную серию и первый измеренный план."""
    runs = []
    first_plan = None
    for run, plan in iter_query_runs(cursor, sql, warmup_runs, measured_runs):
        runs.append(run)
        if first_plan is None and not run["is_warmup"]:
            first_plan = plan
    return {"runs": runs, "analyze_json": first_plan}


def aggregate_runs(runs: list) -> dict:
    """
    Агрегирует измеренные (не прогревочные) запуски в целевую величину.
    Медиана устойчива к единичным выбросам, поэтому отдельные
    запуски не отбрасываются; разброс сохраняется для контроля качества.
    """
    times = [run["execution_time_ms"] for run in runs if not run["is_warmup"]]
    planning_times = [run["planning_time_ms"] for run in runs if not run["is_warmup"]]

    median = statistics.median(times)
    mean = statistics.fmean(times)
    std = statistics.stdev(times) if len(times) > 1 else 0.0
    cv = std / mean if mean > 0 else 0.0

    return {
        "execution_time_ms": median,
        "exec_time_min_ms": min(times),
        "exec_time_max_ms": max(times),
        "exec_time_mean_ms": mean,
        "exec_time_std_ms": std,
        "exec_time_cv": cv,
        "planning_time_ms": statistics.median(planning_times) if None not in planning_times else None,
        "measured_runs": len(times),
        "is_unstable": int(cv > UNSTABLE_CV),
    }

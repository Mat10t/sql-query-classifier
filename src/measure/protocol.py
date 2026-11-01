"""
Протокол измерения фактического времени выполнения SQL-запроса.

Целевая величина t(q) — медиана Execution Time по MEASURED_RUNS запускам
EXPLAIN (ANALYZE, TIMING OFF) после WARMUP_RUNS прогревочных запусков
в «тёплом» режиме (данные уже в кэше). Подробное обоснование —
в docs/stage1.md.
"""

import json
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


def measure_query(cursor, sql: str, warmup_runs: int, measured_runs: int) -> dict:
    """
    Выполняет запрос warmup_runs + measured_runs раз.
    Возвращает все запуски (включая прогревочные) и первый измеренный план.
    """
    runs = []
    first_analyze_json = None

    for run_index in range(warmup_runs + measured_runs):
        is_warmup = run_index < warmup_runs
        analyze_json = run_explain_analyze(cursor, sql)
        root = analyze_json[0]

        runs.append(
            {
                "run_index": run_index,
                "is_warmup": is_warmup,
                "execution_time_ms": root.get("Execution Time", 0),
                "planning_time_ms": root.get("Planning Time", 0),
            }
        )

        if not is_warmup and first_analyze_json is None:
            first_analyze_json = analyze_json

    return {
        "runs": runs,
        "analyze_json": first_analyze_json,
    }


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
        "planning_time_ms": statistics.median(planning_times),
        "measured_runs": len(times),
        "is_unstable": int(cv > UNSTABLE_CV),
    }

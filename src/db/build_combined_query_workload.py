import json
import re
from pathlib import Path


BASE_QUERIES_PATH = Path("data/queries/generated_tpch_queries.json")
STANDARD_QUERIES_DIR = Path("data/queries/tpch_standard_raw")
OUTPUT_PATH = Path("data/queries/combined_tpch_queries.json")


def clean_qgen_sql(sql: str) -> str:
    # Удаляем комментарии вида { ... }
    sql = re.sub(r"\{.*?\}", "", sql, flags=re.DOTALL)

    # Удаляем обычные SQL-комментарии
    sql = re.sub(r"--.*", "", sql)

    # Исправляем некоторые конструкции qgen под PostgreSQL
    sql = re.sub(
        r"date\s*\(\s*'([^']+)'\s*\)",
        r"DATE '\1'",
        sql,
        flags=re.IGNORECASE,
    )

    sql = re.sub(
        r"interval\s+'(\d+)'\s+(day|month|year)(\s*\(\s*\d+\s*\))?",
        r"INTERVAL '\1 \2'",
        sql,
        flags=re.IGNORECASE,
    )

    sql = re.sub(
        r"interval\s*\(\s*(\d+)\s*\)\s+month\s+to\s+month",
        r"INTERVAL '\1 month'",
        sql,
        flags=re.IGNORECASE,
    )

        # qgen иногда добавляет Oracle-style rownum.
    # PostgreSQL его не поддерживает.
    rownum_match = re.search(
        r"\bwhere\s+rownum\s*<=\s*(-?\d+)\s*;?\s*$",
        sql,
        flags=re.IGNORECASE,
    )

    if rownum_match:
        limit_value = int(rownum_match.group(1))

        sql = re.sub(
            r"\bwhere\s+rownum\s*<=\s*-?\d+\s*;?\s*$",
            "",
            sql,
            flags=re.IGNORECASE,
        )

        if limit_value > 0:
            sql = sql.rstrip().rstrip(";") + f"\nLIMIT {limit_value}"

    sql = convert_view_to_cte(sql)
    sql = sql.strip()

    if not sql.endswith(";"):
        sql += ";"

    return sql


def convert_view_to_cte(sql: str) -> str:
    # Q15 в TPC-H создаёт временное представление.
    # Переписываем его в эквивалентный запрос с WITH, чтобы остался один SELECT.
    match = re.search(
        r"create\s+view\s+(\w+)\s*\(([^)]*)\)\s+as\s+(.*?);\s*"
        r"(select\b.*?);\s*drop\s+view\s+\w+\s*;",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return sql

    view_name, columns, view_body, main_select = match.groups()

    return (
        f"with {view_name} ({columns.strip()}) as (\n{view_body.strip()}\n)\n"
        f"{main_select.strip()};"
    )


def load_base_queries():
    with BASE_QUERIES_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_standard_queries():
    # Каждая папка seed_<N> — полный набор из 22 запросов qgen с seed N
    # (см. scripts/generate_tpch_queries.sh)
    queries = []

    for seed_dir in sorted(STANDARD_QUERIES_DIR.glob("seed_*")):
        seed = seed_dir.name.replace("seed_", "")

        for path in sorted(seed_dir.glob("q*.sql")):
            query_number = path.stem.replace("q", "")
            sql = clean_qgen_sql(path.read_text(encoding="utf-8"))

            if "create view" in sql.lower():
                print(f"Skipped {seed_dir.name}/{path.name}: contains CREATE VIEW")
                continue

            queries.append(
                {
                    "id": f"tpch_s{seed}_q{query_number}",
                    "template_id": f"tpch_q{query_number}",
                    "source": "tpch_qgen",
                    "query_type": f"tpch_standard_q{query_number}",
                    "expected_complexity": "heavy",
                    "sql": sql,
                }
            )

    return queries


def remove_duplicates(queries: list) -> list:
    # У некоторых шаблонов TPC-H (Q15, Q18) мало вариантов параметров,
    # и разные seed дают одинаковый текст. Оставляем первый экземпляр,
    # чтобы один и тот же запрос не попал одновременно в train и test.
    seen = set()
    unique = []

    for query in queries:
        key = " ".join(query["sql"].lower().split())

        if key in seen:
            print(f"Skipped {query['id']}: duplicate SQL text")
            continue

        seen.add(key)
        unique.append(query)

    return unique


def main():
    base_queries = load_base_queries()
    standard_queries = load_standard_queries()

    combined_queries = remove_duplicates(base_queries + standard_queries)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(combined_queries, file, ensure_ascii=False, indent=2)

    print(f"Base queries: {len(base_queries)}")
    print(f"Standard TPC-H queries: {len(standard_queries)}")
    print(f"Duplicates removed: {len(base_queries) + len(standard_queries) - len(combined_queries)}")
    print(f"Total queries: {len(combined_queries)}")
    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

from collections import defaultdict
import json
from pathlib import Path


def limit_per_template(queries: list, limit: int) -> list:
    if limit < 1:
        raise ValueError("Лимит числа запросов на шаблон должен быть положительным")
    counts = defaultdict(int)
    selected = []
    for query in queries:
        template = query.get("template_id", query["id"])
        if counts[template] < limit:
            selected.append(query)
            counts[template] += 1
    return selected


def load_queries(path: Path, limit: int | None = None):
    with path.open(encoding="utf-8") as file:
        queries = json.load(file)
    return queries if limit is None else limit_per_template(queries, limit)

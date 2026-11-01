#!/usr/bin/env bash
# Генерация стандартных TPC-H-запросов через qgen с фиксированными seed.
# Каждый seed даёт новый набор параметров для всех 22 шаблонов,
# поэтому один шаблон TPC-H представлен несколькими экземплярами.
#
# Запуск из корня проекта (Linux / WSL):
#   bash scripts/generate_tpch_queries.sh
set -euo pipefail

SCALE_FACTOR="${SCALE_FACTOR:-1}"
SEEDS="${SEEDS:-101 202 303 404 505}"

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DBGEN_DIR="$PROJECT_ROOT/external/tpch-dbgen"
OUTPUT_DIR="$PROJECT_ROOT/data/queries/tpch_standard_raw"

export DSS_QUERY="$DBGEN_DIR/queries"
cd "$DBGEN_DIR"

for seed in $SEEDS; do
    seed_dir="$OUTPUT_DIR/seed_$seed"
    mkdir -p "$seed_dir"

    for i in $(seq 1 22); do
        ./qgen -s "$SCALE_FACTOR" -r "$seed" "$i" > "$seed_dir/q$(printf "%02d" "$i").sql"
    done

    echo "seed $seed: $(ls "$seed_dir" | wc -l) queries -> $seed_dir"
done

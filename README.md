# SQL Query Classifier

Прототип подсистемы оценки ресурсоёмкости SQL-запросов.

Система принимает SQL-запрос, получает его план выполнения через PostgreSQL `EXPLAIN`, извлекает признаки SQL-текста и плана выполнения, после чего с помощью линейной модели классифицирует запрос как лёгкий или тяжёлый.

## Стек

- Python 3.12 или новее
- PostgreSQL 16.4
- scikit-learn
- pandas, numpy, scipy, matplotlib
- psycopg
- sqlparse
- FastAPI
- Docker / Docker Compose

## Основные возможности

- генерация и импорт тестовой БД TPC-H;
- генерация SQL-запросов разной сложности;
- подключение стандартных TPC-H-запросов;
- сбор датасета через `EXPLAIN` и `EXPLAIN ANALYZE`;
- извлечение признаков SQL-запроса через `sqlparse`;
- извлечение признаков плана выполнения PostgreSQL;
- обучение модели `LogisticRegression`;
- вывод метрик качества модели;
- сохранение важности признаков;
- CLI-предсказание для одного SQL-запроса;
- FastAPI endpoint `/predict-complexity`.

## НИР, 7 семестр: этапы 1-5

Документы по этапам:

- [docs/stage1.md](docs/stage1.md) - постановка, целевая величина, протокол повторов;
- [docs/stage2.md](docs/stage2.md) - признаки EXPLAIN, обзор методов, baseline Total Cost;
- [docs/stage3.md](docs/stage3.md) - стенд, корпус запросов, исключение фактических метрик;
- [docs/stage4.md](docs/stage4.md) - группы признаков, расширение корпуса и разбиение по шаблонам.
- [docs/stage5.md](docs/stage5.md) - сравнение Total Cost, регрессии по Total Cost и бинарного классификатора на фиксированных выборках.

### Быстрая проверка (без стенда, по опубликованным данным)

```bash
pip install -r requirements.txt
python -m src.checks.check_collection
python -m src.checks.check_leakage
python -m src.analysis.repeatability
python -m src.analysis.total_cost_baseline
python -m src.db.build_extended_workload --check
python -m src.evaluation.baselines --dataset data/processed/v2/query_dataset.csv --splits reports/stage5/v2/splits.csv --output-dir reports/stage5/v2
```

- `check_collection` сверяет идентификаторы исходных запросов, результатов и планов, число повторов и медианы. На опубликованной серии ожидаются 274 запроса и 1644 завершённых запуска.
- `check_leakage` пересчитывает признаки из сохранённых EXPLAIN-планов и проверяет, что в них нет фактических метрик (ожидается три строки `OK`);
- `repeatability` и `total_cost_baseline` пересчитывают таблицы и графики в `reports/stage1` и `reports/stage2` из `data/processed`.
- Для этапов 4 и 5 используется расширенный корпус из 370 запросов. `build_extended_workload --check` сверяет SQL и состав выборок. Команда `baselines` выше пересчитывает ошибки и прогнозы. На тесте по шаблонам ожидаются MAE 766.18 мс и RMSE 1421.44 мс. [Состав корпуса](docs/stage4.md) и [результаты базовых моделей](docs/stage5.md).

### Полное воспроизведение на стенде

```bash
# 1. Стенд: PostgreSQL 16.4 с фиксированной конфигурацией
docker compose up -d postgres

# 2. Генератор TPC-H (коммит 32f1c1b) и данные SF=1
git clone https://github.com/electrum/tpch-dbgen external/tpch-dbgen
git -C external/tpch-dbgen checkout 32f1c1b92d1664dba542e927d23d86ffa57aa253
make -C external/tpch-dbgen
(cd external/tpch-dbgen && ./dbgen -s 1 -f)
mkdir -p data/raw/tpch && mv external/tpch-dbgen/*.tbl data/raw/tpch/
DB_HOST=localhost DB_PORT=5433 python -m src.db.import_tpch_tbl

# 3. Корпус запросов (qgen с seed 101..505 + собственный генератор)
bash scripts/generate_tpch_queries.sh
python -m src.db.generate_query_workload
python -m src.db.build_combined_query_workload

# 4. Снимок окружения, эксперимент с повторами, сбор датасета
export DB_HOST=localhost DB_PORT=5433
python -m src.db.snapshot_environment --output reports/stage3/new_run/environment.json
python -m src.db.collect_dataset --warmup-runs 0 --runs 15 --limit-per-template 1 \
  --output data/processed/repeatability/query_dataset.csv \
  --measurements-output data/processed/repeatability/measurements.csv \
  --plans-output data/processed/repeatability/plans.jsonl
python -m src.analysis.repeatability
python -m src.db.collect_dataset --label-quantile 0.75
python -m src.db.snapshot_environment --output reports/stage3/new_run/environment_after_collection.json

# 5. Проверки и baseline
python -m src.checks.check_leakage
python -m src.analysis.total_cost_baseline
python -m src.analysis.export_plan_examples
```

Для новой серии надо использовать отдельную папку снимков. До и после сбора надо сравнить значения `statistics.sha256`. Для такого сравнения должны совпадать версия расчёта, схема и перечень полей. В опубликованных снимках использован исходный формат, поэтому их хеши сравнивают только друг с другом. Содержимое таблиц предполагается неизменным в течение серии. После нового импорта или `ANALYZE` надо отдельно сравнить планы, Total Cost и результаты измерений.

Проверка расчёта отпечатка на тестовых данных: `python -m unittest discover -s tests -p test_statistics_fingerprint.py`.

## Локальный запуск через venv

### 1. Создать виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Установить зависимости

```bash
pip install -r requirements.txt
```

### 3. Создать `.env`

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=sql_classifier_bench
DB_USER=sql_classifier
DB_PASSWORD=sql_classifier
```

Для подключения к PostgreSQL из `docker-compose.yml` надо указать `DB_PORT=5433`.

### 4. Проверить подключение к PostgreSQL

```bash
python -m src.db.check_connection
```

## Подготовка TPC-H данных

Данные TPC-H генерируются через `dbgen` из electrum/tpch-dbgen, коммит `32f1c1b` (клонирование и сборка - в разделе "Полное воспроизведение на стенде").

```bash
cd external/tpch-dbgen
./dbgen -s 1 -f
mkdir -p ../../data/raw/tpch
cp *.tbl ../../data/raw/tpch/
cd ../..
```

## Импорт TPC-H в PostgreSQL

```bash
python -m src.db.import_tpch_tbl
```

Скрипт создаёт таблицы TPC-H и импортирует `.tbl`-файлы в PostgreSQL.

## Генерация SQL-нагрузки

### 1. Сгенерировать шаблонные запросы

```bash
python -m src.db.generate_query_workload
```

### 2. Сгенерировать стандартные TPC-H-запросы через qgen

```bash
bash scripts/generate_tpch_queries.sh
```

Скрипт запускает `qgen` для 22 запросов TPC-H с seed 101, 202, 303, 404, 505 и сохраняет их в `data/queries/tpch_standard_raw/seed_<N>/q01.sql ... q22.sql`.

### 3. Объединить запросы

```bash
python -m src.db.build_combined_query_workload
```

Итоговый файл:

```text
data/queries/combined_tpch_queries.json
```

При объединении Q15 (`CREATE VIEW ... ; SELECT ...; DROP VIEW`) переписывается в эквивалентный запрос с `WITH`, а повторяющиеся тексты запросов удаляются. Корпус этапа 3 содержит 274 запроса из 31 шаблона. У каждого есть `template_id` и `source`. Расширение до 370 запросов описано в [этапе 4](docs/stage4.md).

## Проверка SQL-запросов через EXPLAIN

```bash
python src/db/check_tpch_queries.py data/queries/combined_tpch_queries.json
```

## Сбор датасета

```bash
python -m src.db.collect_dataset \
  --queries data/queries/combined_tpch_queries.json \
  --label-quantile 0.75
```

Скрипт:

- выполняет `EXPLAIN` и строит по нему признаки;
- выполняет запрос по протоколу из `src/measure/protocol.py`: 1 прогревочный и 5 измеренных запусков `EXPLAIN (ANALYZE, TIMING OFF)`;
- записывает в `execution_time_ms` медиану измеренных запусков - целевую величину t(q);
- сохраняет датасет в `data/processed/query_dataset.csv`, все запуски - в `data/processed/measurements.csv`, планы - в `data/processed/plans.jsonl`;
- при указанном `--label-quantile` сохраняет описательную метку корпуса в CSV. При обучении бинарная метка вычисляется заново по порогу из train.

Важно:

- `EXPLAIN` используется для признаков до выполнения запроса;
- `EXPLAIN ANALYZE` используется только для целевой величины;
- разрешённые признаки заданы по группам в `src/features/columns.py`, проверка - `python -m src.checks.check_leakage`.

## Обучение модели

```bash
python -m src.model.train_model --dataset data/processed/v2/query_dataset.csv --splits reports/stage5/v2/splits.csv --reports-dir reports/stage5/v2/binary/template
```

Команда обучает классификатор на пяти группах признаков расширенного корпуса. Программа проверяет состав выборок и колонки данных, затем определяет порог по обучающим запросам. Команды для обоих разбиений приведены в [этапе 5](docs/stage5.md#как-проверить).

После обучения сохраняются:

```text
models/query_classifier.joblib
models/scaler.joblib
models/feature_columns.json
reports/stage5/v2/binary/template/metrics.json
reports/stage5/v2/binary/template/feature_importance.csv
```

## CLI-предсказание

Пример лёгкого запроса:

```bash
python -m src.model.predict_query \
  --sql "SELECT c_custkey, c_name FROM customer LIMIT 10;"
```

Пример тяжёлого запроса:

```bash
python -m src.model.predict_query \
  --sql "SELECT c.c_name, COUNT(*) AS cnt, SUM(l.l_extendedprice) AS total FROM customer c JOIN orders o ON c.c_custkey = o.o_custkey JOIN lineitem l ON o.o_orderkey = l.l_orderkey GROUP BY c.c_name ORDER BY total DESC LIMIT 100;"
```

## Запуск FastAPI

```bash
uvicorn src.api.app:app --reload
```

Документация API:

```text
http://127.0.0.1:8000/docs
```

Проверка состояния сервиса:

```text
GET /health
```

Классификация запроса:

```text
POST /predict-complexity
```

Пример тела запроса:

```json
{
  "sql": "SELECT c_custkey, c_name FROM customer LIMIT 10;"
}
```

Пример ответа:

```json
{
  "class": "light",
  "probability_heavy": 0.1234,
  "top_contributions": [
    {
      "feature": "total_cost",
      "contribution": 0.45
    }
  ]
}
```

API принимает только один `SELECT`-запрос. Запросы с `DROP`, `DELETE`, `UPDATE`, `INSERT`, `CREATE` и другими изменяющими операциями блокируются.

## Запуск через Docker

### 1. Запустить контейнеры

```bash
docker compose up --build
```

Будут запущены:

- PostgreSQL;
- FastAPI-приложение.

API будет доступен:

```text
http://127.0.0.1:8000/docs
```

PostgreSQL внутри контейнера доступен с хоста на порту `5433`.

### 2. Импортировать TPC-H данные в Docker PostgreSQL

Во втором терминале:

```bash
source venv/bin/activate
DB_HOST=localhost DB_PORT=5433 python -m src.db.import_tpch_tbl
```

Если таблицы уже импортированы, повторный импорт не нужен. Скрипт пересоздаёт TPC-H-таблицы.

### 3. Остановить контейнеры

```bash
docker compose down
```

Если нужно удалить данные PostgreSQL-контейнера:

```bash
docker compose down -v
```

## Результат прототипа 6 семестра

Бинарный классификатор, обученный на датасете 6 семестра (189 запросов, `reports/metrics.json`). Результаты классификации на корпусе 7 семестра приведены в [этапе 5](docs/stage5.md#бинарная-классификация).

```text
Accuracy: 0.8958
ROC-AUC: 0.9398
Recall для heavy: 1.00
F1-score для heavy: 0.83
```

Наиболее значимые признаки (`reports/feature_importance.csv`):

```text
subquery_count
total_cost
startup_cost
join_count
group_by_count
aggregate_func_count
query_length
```

## Ограничения

- модель обучена на тестовой БД TPC-H;
- при смене структуры БД, объёма данных или типа запросов модель желательно переобучать;
- `EXPLAIN` тоже требует времени, но обычно значительно меньше, чем выполнение тяжёлого запроса;
- прототип предназначен для предварительной оценки запроса, а не для точного прогноза времени выполнения.
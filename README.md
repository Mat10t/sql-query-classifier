# SQL Query Classifier

Прототип подсистемы оценки ресурсоёмкости SQL-запросов.

Система принимает SQL-запрос, получает его план выполнения через PostgreSQL `EXPLAIN`, извлекает признаки SQL-текста и плана выполнения, после чего с помощью линейной модели классифицирует запрос как лёгкий или тяжёлый.

## Стек

- Python 3.12
- PostgreSQL
- scikit-learn
- pandas
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

## Структура проекта

```text
sql-query-classifier/
├── data/
│   ├── processed/
│   └── queries/
├── models/
├── reports/
├── src/
│   ├── api/
│   ├── db/
│   ├── features/
│   └── model/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

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

### 4. Проверить подключение к PostgreSQL

```bash
python -m src.db.check_connection
```

## Подготовка TPC-H данных

Данные TPC-H генерируются через `dbgen`.

Пример:

```bash
cd external/tpch-dbgen
./dbgen -s 1
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
mkdir -p data/queries/tpch_standard_raw

cd external/tpch-dbgen

export DSS_QUERY=$PWD/queries

for i in $(seq 1 22); do
    ./qgen -s 1 $i > ../../data/queries/tpch_standard_raw/q$(printf "%02d" $i).sql
done

cd ../..
```

### 3. Объединить запросы

```bash
python -m src.db.build_combined_query_workload
```

Итоговый файл:

```text
data/queries/combined_tpch_queries.json
```

Один из стандартных TPC-H-запросов может быть пропущен, если содержит `CREATE VIEW`, так как API-прототип работает только с `SELECT`.

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

- выполняет `EXPLAIN`;
- выполняет `EXPLAIN ANALYZE`;
- извлекает признаки;
- сохраняет датасет в `data/processed/query_dataset.csv`;
- ставит метку `label` по 75% квантилю времени выполнения.

Важно:

- `EXPLAIN` используется для признаков до выполнения запроса;
- `EXPLAIN ANALYZE` используется только при сборе обучающего датасета;
- `execution_time_ms` не используется как входной признак модели.

## Обучение модели

```bash
python -m src.model.train_model
```

После обучения сохраняются:

```text
models/query_classifier.joblib
models/scaler.joblib
models/feature_columns.json
reports/metrics.json
reports/feature_importance.csv
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

## Текущий результат модели

Пример результата после обучения:

```text
Accuracy: 0.8958
ROC-AUC: 0.9491
Recall для heavy: 1.00
F1-score для heavy: 0.83
```

Наиболее значимые признаки:

```text
total_cost
subquery_count
startup_cost
join_count
group_by_count
aggregate_func_count
window_func_count
```

## Ограничения

- модель обучена на тестовой БД TPC-H;
- при смене структуры БД, объёма данных или типа запросов модель желательно переобучать;
- `EXPLAIN` тоже требует времени, но обычно значительно меньше, чем выполнение тяжёлого запроса;
- прототип предназначен для предварительной оценки запроса, а не для точного прогноза времени выполнения.
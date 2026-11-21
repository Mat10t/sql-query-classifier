# Этап 5. Базовые модели на фиксированных выборках

На корпусе из 370 запросов и 39 шаблонов проверены три базовых метода. В основном разбиении модели обучены на 308 запросах и проверены на 62 запросах из 10 новых шаблонов. В сравнительном случайном разбиении в обучении 277 запросов, в тесте 93. Во всех расчётах используются [выборки этапа 4](stage4.md#разбиение-на-обучение-и-тест).

## Как получены прогнозы

- Готовая оценка PostgreSQL - поле `Total Cost` корневого узла плана EXPLAIN. Чем больше значение, тем дольше, по прогнозу, выполняется запрос. Единицы стоимости позволяют сравнить порядок запросов. Для получения времени требуется калибровка.
- Линейная регрессия обучена отдельно в каждом режиме методом наименьших квадратов. Модель имеет вид `log(1 + t) = a + b * Total Cost`, где `t` измеряется в миллисекундах, логарифм натуральный. Единственный вход - исходный Total Cost. Коэффициенты `a` и `b` найдены только по train. Прогноз времени равен `exp(max(0, a + b * Total Cost)) - 1`. Нижняя граница соответствует нулевой длительности.
- Бинарный классификатор предсказывает, превысит ли время порог тяжёлого запроса. Он использует 22 признака плана и SQL. Порог равен 75-му процентилю времени на train, масштабирование также обучено на train. Подробнее о метках и составе признаков в [описании этапа 4](stage4.md).

## Порядок запросов

Для обоих разбиений у регрессии положительный коэффициент при Total Cost и положительные тестовые прогнозы. Поэтому порядок запросов, включая равные оценки, совпал у двух методов.

| Разбиение | Запросов в тесте | Spearman | Kendall | Pairwise accuracy (число пар) | Pairwise для непересекающихся диапазонов (число пар) |
|---|---:|---:|---:|---:|---:|
| template | 62 | 0.895 | 0.726 | 0.861 (1891) | 0.874 (1816) |
| random | 93 | 0.951 | 0.820 | 0.908 (4226) | 0.929 (4025) |

Обычная pairwise accuracy учитывает все пары с разными медианами времени. Верный порядок даёт один балл, равенство прогнозов - половину. В последнем столбце учтены только пары, у которых самый долгий из пяти измеренных запусков одного запроса быстрее самого короткого запуска другого. В основном тесте среди 1816 таких пар у 1584 порядок совпал и у 5 прогнозы равны. Получается `(1584 + 0.5 * 5) / 1816 = 0.874` с округлением. Время отдельных запусков использовано только при оценке.

## Ошибка прогноза времени

MAE - средняя абсолютная ошибка, RMSE - корень из средней квадратичной ошибки. Первые два показателя рассчитаны после обратного преобразования прогноза в миллисекунды, последние два - на шкале обучения.

| Разбиение | MAE, мс | RMSE, мс | MAE для log(1 + t) | RMSE для log(1 + t) |
|---|---:|---:|---:|---:|
| template | 766.18 | 1421.44 | 1.970 | 2.495 |
| random | 3640.04 | 28935.89 | 1.306 | 1.600 |

На новых шаблонах регрессия по Total Cost дала среднюю абсолютную ошибку 766.18 мс. Для сравнения, постоянный прогноз медианой времени обучения (9.07 мс для каждого запроса) даёт MAE 800.50 мс. В случайном разбиении наибольшая ошибка получена для запроса `tpch_s404_q18`: прогноз 279624.93 мс при фактическом времени 1624.70 мс. Такой промах особенно сильно влияет на RMSE. [Прогнозы по запросам](../reports/stage5/v2/predictions.csv), [метрики и коэффициенты](../reports/stage5/v2/metrics.json), [расчёт постоянного прогноза](../reports/stage5/v2/coverage.json).

## Бинарная классификация

Precision, Recall и F1 приведены для класса тяжёлых запросов. Порог определён по времени обучающих запросов.

| Разбиение | Порог, мс | Accuracy | ROC-AUC | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| template | 515.768 | 0.726 | 0.560 | 0.818 | 0.375 | 0.514 |
| random | 521.07 | 0.914 | 0.961 | 0.778 | 1.000 | 0.875 |

В основном тесте классификатор обнаружил 9 из 24 тяжёлых запросов. Из 38 остальных к тяжёлым ошибочно отнесены 2. [Матрица ошибок для template](../reports/stage5/v2/binary/template/metrics.json) и [для random](../reports/stage5/v2/binary/random/metrics.json).

## Как проверить

После установки зависимостей команды проверки выполняются в Bash из корня проекта.

```bash
python -m src.db.build_extended_workload --check
dataset=data/processed/v2/query_dataset.csv
plans=data/processed/v2/plans.jsonl
splits=reports/stage5/v2/splits.csv
out=$(mktemp -d)
python -m src.checks.check_collection --queries data/queries/v2/queries.json --dataset "$dataset" --measurements data/processed/v2/measurements.csv --plans "$plans"
python -m src.checks.check_leakage --dataset "$dataset" --plans "$plans"
python -m src.evaluation.baselines --dataset "$dataset" --splits "$splits" --output-dir "$out"
python -m src.analysis.extended_corpus --output "$out/coverage.json"
for mode in template random; do
  python -m src.model.train_model --dataset "$dataset" --splits "$splits" --split "$mode" --model-dir "$out/models/$mode" --reports-dir "$out/binary/$mode"
done
```

Перед сбором новой серии надо запустить стенд, описанный в [README](../README.md#полное-воспроизведение-на-стенде). Следующие команды сохраняют новые измерения и снимки в отдельный каталог. В сохранённой серии контрольная сумма статистики PostgreSQL совпала [до сбора](../reports/stage5/v2/environment_before.json) и [после него](../reports/stage5/v2/environment_after.json).

```bash
export DB_HOST=localhost DB_PORT=5433
queries=data/queries/v2/queries.json
series=$(mktemp -d)
python -m src.db.snapshot_environment --queries "$queries" --output "$series/environment_before.json"
python -m src.db.collect_dataset --queries "$queries" --label-quantile 0.75 --output "$series/query_dataset.csv" --measurements-output "$series/measurements.csv" --plans-output "$series/plans.jsonl"
python -m src.db.snapshot_environment --queries "$queries" --output "$series/environment_after.json"
```

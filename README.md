# Localhosters — HackAlem AI

## Назначение

Почасовой прогноз нормализованной мощности двух турбин на горизонте 48 часов. Система воспроизводит ежедневные выпуски с погодой, которая была опубликована на момент решения. [Условие кейса](task%20context/HackAlemAIAgenticAI.html), [план задач](docs/research/README.md).

## Архитектура

`Clock → архив погоды → проверка данных → модель → решение планировщика → CSV + trace`. В [архитектуре](docs/architecture.md) есть схема, границы LLM и кода, таблица решений и триггеры пересчёта. В офлайн-режиме работает `ScriptedPlanner`; режим OpenAI (`--llm openai`, ключ `OPENAI_API_KEY`, модель `gpt-5.4-mini`) принимает те же решения через LLM. `make llm-replay` прогоняет весь февраль с LLM: 58 из 58 решений совпали с правилами, 0 откатов, $0.095 за месяц — [отчёт](reports/llm_replay_test.md).

## Как гарантируем отсутствие утечки

Каждый сохранённый ран имеет `run_init_utc`. Для ECMWF IFS применяем лаги по циклам: 00Z +8 ч, 06Z +7 ч, 12Z +8 ч, 18Z +7 ч. Выпуск 31 января 19:00 UTC ещё не может читать 12Z ран; 20:00 — может. Модель видит прогнозы из as-issued Single Runs. Схема интервалов и ограничения источников: [as-of-convention](docs/research/as-of-convention.md). SCADA размечена фиксированным UTC+6.
Доказательство таймзоны: [tz_xcorr.png](docs/figures/tz_xcorr.png), обработка через `Etc/GMT-6` и [scripts/tz_check.py](scripts/tz_check.py).

## Метрика, которую надо побить (LOC-9)

Честный case-compliant бейзлайн Previous Runs `ws100` → refit-кривая даёт **MAE 0.20–0.22** по нормализованной мощности (h1–24) и около **0.22** на h25–48. Цель модели — MAE ≤0.19 (skill ≥10%), приемлемый результат — ≤0.22. ERA5 и будущий SCADA-ветер в эти бейзлайны не входят: это недоступные на issue-time потолки. Воспроизводимые таблицы: [docs/research/baselines.md](docs/research/baselines.md), полный CSV: [reports/baselines.csv](reports/baselines.csv).

## LightGBM v1 (LOC-10)

`make train` офлайн собирает lead-aligned признаки из явных ECMWF IFS Single
Runs и leak-safe Previous Runs, обучает pooled-модель T1/T2 и сравнивает её с
v0 на Feb 2025 и Jan 2026. Результаты, срезы h1–24 / h25–48 и feature
importance: [docs/research/lightgbm-v1.md](docs/research/lightgbm-v1.md).

## Технологии

Python 3.12, uv, pandas/pyarrow, LightGBM, Pydantic AI, Open-Meteo Single Runs. Числовая v0-модель — MOS к ветру + эмпирическая логистическая кривая мощности; LightGBM v1 использует те же as-issued выпуски и вторичные Previous Runs. Архив 116 февральских ранов, 31 dev-ран и HTTP-клиент Ramazan описаны в [документе погоды](docs/03_WEATHER_ARCHIVE.md) и [бэктесте](docs/research/backtest-v0.md).

## Установка

```bash
make setup
```

Для Docker: `make docker` при запущенном Docker daemon. Dockerfile использует `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`; контейнер по умолчанию запускает офлайн-проверку.

## Запуск

Офлайн-бэктест по закоммиченному архиву (сабмит v1; `make backtest-v0` — эталон v0):

```bash
make backtest-v1
```

Каждый из 29 выпусков проходит полный цикл агента (погода → проверка данных → модель → решение → трейс), а в 20:00 UTC, когда публикуется ран 12Z, агент делает пересчёт. Прогоны лежат в [`runs/backtest/test/`](runs/backtest/test) — по папке на выпуск с `trace.jsonl`, `decision.json`, `comparison.json`, `report.md`. Сабмит собирается из прогнозов агента и совпадает с прямым расчётом модели (проверяется в `make verify`). Бэктест создаёт [CSV по выпускам](submission/forecast_test_dayahead_v1.csv), [CSV пересчётов](submission/forecast_test_intraday_v1.csv), [CSV по часам](submission/forecast_test_hourly_v1.csv) и агрегат по станции. Первый содержит 29 × 48 × 2 = 2 784 строки. Второй — 672 часа февраля × 2 турбины = 1 344 строки, с отдельными точками для первых и вторых суток. `p10/p90` — эмпирические квантили остатков v0, подогнанные на обучающем периоде (до LOC-11).

Один issue с погодой из реального архива и моделью v0, затем пересчёт после публикации 12Z:

```bash
uv run --frozen python -m windagent issue --at 2026-01-31T18:00Z --llm scripted --model-adapter windagent.model.v0:predict_power
uv run --frozen python -m windagent issue --at 2026-01-31T20:00Z --llm scripted --model-adapter windagent.model.v0:predict_power
```

Выход каждого запуска: `runs/<timestamp>-<id>/{forecast.csv,inputs.json,dq_report.json,comparison.json,decision.json,trace.jsonl,report.md,memory.json,status.json}`. Результаты разделены по версиям. Синтетический режим запускается отдельно: `make demo`, каждый файл там обозначен `prediction_kind=demo`.

Интерактивный дашборд — все 60 выпусков (январь с фактами, февраль), прогноз с P10–P90, пересчёт 18:00 → 20:00 UTC, трейс агента по шагам:

```bash
make dashboard        # экспорт данных + http://127.0.0.1:5173
```

Развёрнутая версия: https://windagent-localhosters.pages.dev (закрыта паролем — в данных SCADA организаторов; логин `localhosters`, пароль у команды).

## Previous Runs для пяти моделей (LOC-15)

Почасовые признаки `previous_day1/day2` за доступную историю каждой модели,
исходные JSON и Parquet находятся в `data/nwp_cache/previous_runs/`.
Повторная сборка без сети:

```bash
OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m windagent.dump_previous_runs
uv run --frozen python research/skill_benchmark.py --turbine T1
```

Схема данных, покрытие, пропуски и skill: [docs/research/nwp-sources.md](docs/research/nwp-sources.md).

## Зависимости

Версии зафиксированы в `uv.lock`; Python-пакет и dev-зависимости — в `pyproject.toml`. Для `make backtest-v0` сеть и API-ключ не нужны. Происхождение данных: [research/README.md](research/README.md).

## Параметры окружения

Шаблон — [.env.example](.env.example). Основные: `ISSUE_HOUR_UTC=18`, `SCADA_TZ_OFFSET_HOURS=6`, `HORIZON_HOURS=48`, `OPEN_METEO_CACHE_ONLY=1`, `LLM_MODE=scripted`, `POINT_ESTIMATE=median`. Консервативные задержки NWP заданы по циклам в `windagent/clock.py`; `AVAIL_LAG_HOURS` пока относится только к будущим не-ECMWF адаптерам. [Допущения](docs/assumptions.md) отмечают вопросы организаторам и план смены дефолтов.

## Проверка основного сценария

```bash
make verify
```

Проверка занимает секунды: два выпуска 06Z→12Z, полный trace из 11 шагов, отказ от будущего рана в 19:00, контроль всех 2 784 строк CSV, 1 344 часовых строк и реальный пересчёт на архиве. Ожидаемый финал — две строки `PASS`. Дополнительно `make backtest-dev` считает январские метрики; фактов февраля 2026 в предоставленных файлах нет.

## Данные и модель

Входные CSV — в `task context/`. SCADA-пакет LOC-8 — `windagent/data/scada.py`. v0 калибрует линейный MOS и эмпирические интервалы на ноябре–декабре 2025, затем применяет модель к архивному прогнозу ветра. Для v1 адаптер `windagent.model.v0:predict_power` заменяется контрактом LOC-12 без изменения схемы issue.

## Результаты

Сабмит — LightGBM v1 (бленд с v0) через агента: [CSV по выпускам](submission/forecast_test_dayahead_v1.csv) (2 784 строки), [CSV по часам](submission/forecast_test_hourly_v1.csv) (1 344 строки), [пересчёты 20:00 UTC](submission/forecast_test_intraday_v1.csv). Фактов февраля 2026 в данных нет, поэтому качество меряем as-of на двух окнах с фактами тем же путём агента и holdout-моделью:

| Окно | Модель | MAE T1 | MAE T2 | Медиана 7 сут. (T1 / T2) | Покрытие P10–P90 |
|---|---|---:|---:|---:|---:|
| Jan 2026 (dev) | **v1** | **0.171** | **0.175** | 0.294 / 0.288 | 0.80 |
| Jan 2026 (dev) | v0 | 0.174 | 0.177 | | 0.80 |
| Feb 2025 (тот же сезон) | **v1** | **0.165** | **0.188** | 0.339 / 0.304 | 0.80 |
| Feb 2025 (тот же сезон) | v0 | 0.172 | 0.192 | | 0.79 |

MAE — по нормализованной мощности на всём горизонте 48 ч; порог ≤0.22 и цель ≤0.19 выполнены. P10/P90 пока эмпирические (квантили остатков v0), квантильные модели — LOC-11. Блоки h1–24 / h25–48, режим `weather_explainable` и skill: [отчёт v1](docs/research/backtest-v1.md), `reports/backtest_v1_{dev,feb2025}*.csv`; v0 — [отчёт v0](docs/research/backtest-v0.md). Воспроизвести: `make backtest-dev`, `make backtest-feb2025`.

## Ограничения и развитие

Бэктест исполняет day-ahead 18:00 UTC и пересчёт 20:00 UTC на каждый февральский день; в январском кеше только раны 06Z, поэтому там пересчётов нет. Эмпирические P10/P90 требуют проверки покрытия; live-цикл с фактическими измерениями ещё не подключён. Дашборд показывает все выпуски и сцену re-issue на каждый февральский день; [сценарий демо](docs/demo-storyboard.md). В [rubric-map](docs/research/rubric-map.md) указан статус доказательств по критериям жюри.

## Почему не X

`Historical Forecast` и ERA5 не используются для февральского replay: они не являются as-issued прогнозом. Внешний LLM не нужен для численного прогноза и не может менять выбранный ран или неисполненную коррекцию. Подробный ADR — в [архитектуре](docs/architecture.md).

## Attribution

Погода: [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api), ECMWF IFS; запросы, grid, время выгрузки и хеши — в `data/nwp_cache/manifest.json`. Условие и SCADA предоставлены организаторами HackAlem AI.

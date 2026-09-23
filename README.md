# Localhosters — HackAlem AI

## Назначение

Почасовой прогноз нормализованной мощности двух турбин на горизонте 48 часов. Система воспроизводит ежедневные выпуски с погодой, которая была опубликована на момент решения. [Условие кейса](task%20context/HackAlemAIAgenticAI.html), [план задач](docs/research/README.md).

## Архитектура

`Clock → архив погоды → проверка данных → модель → решение планировщика → CSV + trace`. В [архитектуре](docs/architecture.md) есть схема, границы LLM и кода, таблица решений и триггеры пересчёта. В офлайн-режиме работает `ScriptedPlanner`; режим OpenAI (`--llm openai`, ключ `OPENAI_API_KEY`) принимает те же решения через LLM.

## Как гарантируем отсутствие утечки

Каждый сохранённый ран имеет `run_init_utc`. Для ECMWF IFS применяем лаги по циклам: 00Z +8 ч, 06Z +7 ч, 12Z +8 ч, 18Z +7 ч. Выпуск 31 января 19:00 UTC ещё не может читать 12Z ран; 20:00 — может. Модель видит прогнозы из as-issued Single Runs. Схема интервалов и ограничения источников: [as-of-convention](docs/research/as-of-convention.md). SCADA размечена фиксированным UTC+6.
Доказательство таймзоны: [tz_xcorr.png](docs/figures/tz_xcorr.png), обработка через `Etc/GMT-6` и [scripts/tz_check.py](scripts/tz_check.py).

## Технологии

Python 3.12, uv, pandas/pyarrow, Pydantic AI, Open-Meteo Single Runs. Числовая v0-модель — MOS к ветру + эмпирическая логистическая кривая мощности; LightGBM v1 готовит Akylbek (LOC-10/12). Архив 116 февральских ранов, 31 dev-ран и HTTP-клиент Ramazan описаны в [документе погоды](docs/03_WEATHER_ARCHIVE.md) и [бэктесте](docs/research/backtest-v0.md).

## Установка

```bash
make setup
```

Для Docker: `make docker` при запущенном Docker daemon. Dockerfile использует `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`; контейнер по умолчанию запускает офлайн-проверку.

## Запуск

Офлайн-бэктест по закоммиченному архиву:

```bash
make backtest-v0
```

Он создаёт [CSV по выпускам](submission/forecast_test_dayahead_v0.csv), [CSV по часам](submission/forecast_test_hourly_v0.csv) и агрегат по станции. Первый содержит 29 × 48 × 2 = 2 784 строки. Второй — 672 часа февраля × 2 турбины = 1 344 строки, с отдельными точками для первых и вторых суток. `p10/p90` — эмпирические квантили остатков, подогнанные на обучающем периоде.

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

Тестовые CSV сформированы офлайн. Показатели качества скрытого февраля неизвестны. На январском dev-окне v0 даёт MAE **0.174** для T1 и **0.177** для T2 (нормализованная мощность, обе части горизонта); persistence ≈0.335. Полные метрики и покрытие — в [отчёте](docs/research/backtest-v0.md) и `reports/backtest_v0_dev.csv`. Следы отдельного выпуска можно изучить в `trace.jsonl` и `report.md`.

## Ограничения и развитие

Текущий бэктест исполняет day-ahead 18:00 UTC и одну сцену пересчёта. Эмпирические P10/P90 требуют проверки покрытия; live-цикл с фактическими измерениями ещё не подключён. Дашборд показывает все выпуски и сцену re-issue на каждый февральский день; [сценарий демо](docs/demo-storyboard.md). В [rubric-map](docs/research/rubric-map.md) указан статус доказательств по критериям жюри.

## Почему не X

`Historical Forecast` и ERA5 не используются для февральского replay: они не являются as-issued прогнозом. Внешний LLM не нужен для численного прогноза и не может менять выбранный ран или неисполненную коррекцию. Подробный ADR — в [архитектуре](docs/architecture.md).

## Attribution

Погода: [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api), ECMWF IFS; запросы, grid, время выгрузки и хеши — в `data/nwp_cache/manifest.json`. Условие и SCADA предоставлены организаторами HackAlem AI.

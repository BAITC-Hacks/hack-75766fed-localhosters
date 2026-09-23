# Localhosters — HackAlem AI

## Назначение

Почасовой прогноз нормализованной мощности двух турбин на горизонте 48 часов. Система воспроизводит ежедневные выпуски с погодой, которая была опубликована на момент решения. [Условие кейса](task%20context/HackAlemAIAgenticAI.html), [план задач](docs/research/README.md).

## Архитектура

`Clock → архив погоды → проверка данных → модель → решение планировщика → CSV + trace`. В [архитектуре](docs/architecture.md) есть схема, границы LLM и кода, таблица решений и триггеры пересчёта. В офлайн-режиме работает `ScriptedPlanner`; режим Anthropic требует ключа и ещё проходит интеграцию.

## Как гарантируем отсутствие утечки

Каждый сохранённый ран имеет `run_init_utc`. Для ECMWF IFS применяем лаги по циклам: 00Z +8 ч, 06Z +7 ч, 12Z +8 ч, 18Z +7 ч. Выпуск 31 января 19:00 UTC ещё не может читать 12Z ран; 20:00 — может. Модель видит прогнозы из as-issued Single Runs. Схема интервалов и ограничения источников: [as-of-convention](docs/research/as-of-convention.md). SCADA размечена фиксированным UTC+6.

## Технологии

Python 3.12, uv, pandas/pyarrow, Pydantic AI, Open-Meteo Single Runs. Числовая v0-модель — MOS к ветру + эмпирическая логистическая кривая мощности; LightGBM v1 готовит Akylbek (LOC-10/12). Архив 116 ранов и HTTP-клиент Ramazan описаны в [документе погоды](docs/03_WEATHER_ARCHIVE.md).

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

Он создаёт [CSV по выпускам](submission/forecast_feb2026_dayahead_v0.csv) и [CSV по часам](submission/forecast_feb2026_hourly_v0.csv). Первый содержит 29 × 48 × 2 = 2 784 строки. Второй — 672 часа февраля × 2 турбины = 1 344 строки, с отдельными точками для первых и вторых суток. `p10/p90` в v0 оставлены пустыми: интервальная модель ещё не калибрована.

Один issue с погодой из реального архива и моделью v0, затем пересчёт после публикации 12Z:

```bash
uv run --frozen python -m windagent issue --at 2026-01-31T18:00Z --llm scripted --model-adapter windagent.models.v0:predict
uv run --frozen python -m windagent issue --at 2026-01-31T20:00Z --llm scripted --model-adapter windagent.models.v0:predict
```

Выход каждого запуска: `runs/<timestamp>-<id>/{forecast.csv,inputs.json,dq_report.json,comparison.json,decision.json,trace.jsonl,report.md,memory.json,status.json}`. Результаты разделены по версиям. Синтетический режим запускается отдельно: `make demo`, каждый файл там обозначен `prediction_kind=demo`.

## Зависимости

Версии зафиксированы в `uv.lock`; Python-пакет и dev-зависимости — в `pyproject.toml`. Для `make backtest-v0` сеть и API-ключ не нужны. Происхождение данных: [research/README.md](research/README.md).

## Параметры окружения

Шаблон — [.env.example](.env.example). Основные: `ISSUE_HOUR_UTC=18`, `SCADA_TZ_OFFSET_HOURS=6`, `HORIZON_HOURS=48`, `OPEN_METEO_CACHE_ONLY=1`, `LLM_MODE=scripted`, `POINT_ESTIMATE=median`. Консервативные задержки NWP заданы по циклам в `windagent/clock.py`; `AVAIL_LAG_HOURS` пока относится только к будущим не-ECMWF адаптерам. [Допущения](docs/assumptions.md) отмечают вопросы организаторам и план смены дефолтов.

## Проверка основного сценария

```bash
make verify
```

Проверка занимает секунды: два выпуска 06Z→12Z, полный trace из 11 шагов, отказ от будущего рана в 19:00, контроль всех 2 784 строк CSV, 1 344 часовых строк и реальный пересчёт на архиве. Ожидаемый финал — две строки `PASS`. MAE на январском dev-окне будет добавлен после LOC-9/17; фактов февраля 2026 в предоставленных файлах нет.

## Данные и модель

Входные CSV — в `task context/`. Ресёрч-код SCADA — `research/scada_load.py`, боевой пакет LOC-8 готовит Akylbek. v0 калибрует линейный MOS на ноябре–декабре 2025, затем применяет его к архивному прогнозу ветра и эмпирической кривой. Это воспроизводимый ориентир, не проверенная точность. Для v1 адаптер `windagent.models.v0:predict` заменяется контрактом LOC-12 без изменения схемы issue.

## Результаты

Тестовые CSV сформированы офлайн. Показатели качества скрытого февраля неизвестны. Метрики Jan 2026, сравнение с persistence и квалификация v1 появятся после LOC-9/10. Следы отдельного выпуска можно изучить в `trace.jsonl` и `report.md`.

## Ограничения и развитие

Текущий бэктест исполняет day-ahead 18:00 UTC и одну сцену пересчёта. Нет калиброванных P10/P90, полной оценки dev и live-цикла с фактическими измерениями. Дашборд LOC-26 показывает срез 15–19 января и сцену re-issue; [сценарий демо](docs/demo-storyboard.md). В [rubric-map](docs/research/rubric-map.md) указан статус доказательств по критериям жюри.

## Почему не X

`Historical Forecast` и ERA5 не используются для февральского replay: они не являются as-issued прогнозом. Внешний LLM не нужен для численного прогноза и не может менять выбранный ран или неисполненную коррекцию. Подробный ADR — в [архитектуре](docs/architecture.md).

## Attribution

Погода: [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api), ECMWF IFS; запросы, grid, время выгрузки и хеши — в `data/nwp_cache/manifest.json`. Условие и SCADA предоставлены организаторами HackAlem AI.

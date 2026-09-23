# Бэктест v0: as-of прогноз на реальных архивных ранах ECMWF IFS

Ядро MVP (LOC-16, LOC-17). Одна команда — 29 dayahead-выпусков за тестовый период на ранах,
которые были публично доступны на момент выпуска, и почасовой файл для сопоставления с актуалами.

## Запуск

```bash
uv venv .venv && uv pip install -r requirements-lock.txt      # один раз
PYTHONPATH=. .venv/bin/python -m windagent.model.v0 --fit      # models/v0_params.json (уже в репо)
PYTHONPATH=. .venv/bin/python -m windagent.backtest --window test   # submission/forecast_test_*.csv
PYTHONPATH=. .venv/bin/python -m windagent.backtest --window dev    # + reports/backtest_v0_dev.csv (MAE)
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_clock_no_leakage.py
```

Всё офлайн: раны лежат в `data/nwp/single_runs_ecmwf_ifs_{feb2026,jan2026}.parquet`
(`python -m windagent.dump_weather` и `scripts/dump_dev_runs.py` пересобирают их через кеш LOC-14).

## As-of конвенция (`windagent/clock.py`)

| Ран (UTC) | Публикация open data | Правило доступности |
|---|---|---|
| 00Z | ≈07:34 | init + 8 ч |
| 06Z | ≈12:27 | init + 7 ч |
| 12Z | ≈19:34 | init + 8 ч |
| 18Z | ≈00:27 (+1 день) | init + 7 ч |

Выпуск dayahead: **18:00 UTC дня D−1 = 00:00 по часам SCADA дня D** (SCADA — фиксированный UTC+6).
Горизонт 48 ч от выпуска: сутки D и D+1. Последний доступный ран на 18:00 UTC — **06Z того же дня**
(lead 12–59 ч). 12Z становится доступен в 20:00 UTC — это сцена re-issue для агента.
Константа «+7 ч» пропускала бы 12Z в 19:00 UTC — поэтому задержка per-cycle, и `tests/test_clock_no_leakage.py`
проверяет каждую строку сабмита: `run_init + lag[cycle] ≤ issue_time`, `target ≥ issue`, а также
что в predict-пути нет Historical Forecast / Archive / ERA5.

## Модель v0 (`windagent/model/v0.py`)

`ws_site = a·ws100_NWP + b` (MOS, подгонка на Previous Runs day1 vs SCADA-ветер, ноябрь–декабрь 2025,
T1+T2 pooled, n = 2 920 ч; bias NWP по ветру −1.38 м/с) → логистическая кривая
`p = 1/(1+exp(−0.705·(ws − 7.89)))` → clip [0.01, 0.99]. P10/P90 — эмпирические квантили остатков по 4 бинам p.
Январь 2026 в подгонке не участвует. Контракт LOC-12: `predict_power(request) -> PowerForecast`,
`prediction_kind="model"` — подключается к runtime агента как `--model-adapter windagent.model.v0:predict_power`.

## Результат на dev-окне (январь 2026, 31 выпуск, as-of, факты SCADA есть)

| Модель | Турбина | h1–24 | h25–48 | all | skill vs median_7d |
|---|---|---|---|---|---|
| **v0 MOS+кривая** | T1 | **0.164** | 0.184 | **0.174** | +41 % |
| v0 MOS+кривая | T2 | 0.168 | 0.186 | 0.177 | +39 % |
| last_value (persistence) | T1 | 0.311 | 0.361 | 0.335 | −14 % |
| median_7d | T1 | 0.296 | 0.292 | 0.294 | 0 |

MAE в долях от 2.5 МВт. Bias v0 ≈ +0.04 (лёгкий перепрогноз). Цель фазы была ≤0.19 — v0 уже её выполняет;
LightGBM v1 (LOC-10) должен побить 0.174, иначе остаёмся на v0.

## Выход

- `submission/forecast_test_dayahead_v0.csv` — 29 × 48 × 2 = 2 784 строки: `issue_time_utc/scada, target_time_scada/utc,
  turbine, lead_h, nwp_run_init_utc, nwp_lead_h, issue_kind, p10, p50, p90, outside_test_period, model_version`.
  Последний выпуск (28.02 18:00 UTC) покрывает 1–2 марта — строки помечены `outside_test_period=True`.
- `submission/forecast_test_hourly_v0.csv` — строка на час × турбина за 01.02 00:00 – 28.02 23:00 SCADA (1 344 строки):
  `p50` из выпуска накануне (lead 0–23), `p50_h25_48` из выпуска за двое суток, `power_mw = 2.5·p50`.
- `submission/forecast_test_hourly_plant_v0.csv` — `plant_mw`, `energy_mwh` по ВЭС (672 часа).
- `reports/backtest_v0_dev.csv` — таблица метрик выше.

## Что дальше

- LOC-23: прогнать те же 29 выпусков через runtime агента (`run_issue`) с `--model-adapter windagent.model.v0:predict_power`;
  нормализованный кеш `NwpForecast` строится из тех же parquet.
- LOC-10/12: заменить `predict_series` на LightGBM через тот же контракт; сравнить на этой же таблице.
- Открытые вопросы организаторам (см. `questions.md`): момент выпуска, формат, метрика.

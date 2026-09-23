# research/ — рабочий код и данные фазы ресёрча

Курированный код и данные ресёрч-агентов (2026-09-23). Точка старта для LOC-8 (hourly SCADA в UTC),
LOC-14 (клиент Open-Meteo + дамп Single Runs) и LOC-15 (дамп Previous Runs + skill-таблица):
не с нуля, а с проверенных функций и закоммиченного кеша.

## Запуск

```
python3 -m pip install pandas numpy requests     # только это; Python 3.12 проверен
python3 research/scada_load.py                   # offline
python3 research/tz_check.py                     # offline (data/era5)
python3 research/skill_benchmark.py              # offline (data/nwp_cache/previous_runs_*)
python3 research/dump_single_runs.py             # offline: CSV уже есть -> выходит сразу; --force качает 116 ранов
python3 research/openmeteo_client.py [--live]    # без --live сеть не нужна
```

Всё запускается из корня репо. `OPEN_METEO_CACHE_ONLY=1` запрещает сеть: cache miss -> `CacheMiss` с
путём ключа (режим для жюри и CI). Без переменной ответы API кешируются в `data/nwp_cache/<endpoint>/`.
Никаких абсолютных путей: скрипты находят репо через `Path(__file__).resolve().parents[1]`.

## Скрипты

| Файл | Что делает | Сеть | Из чего собран |
|---|---|---|---|
| `openmeteo_client.py` | `om_get` (retry 429/5xx, JSON-кеш), `previous_runs`, `previous_runs_chunked`, `single_run`, `archive_era5`, `historical_forecast`, `hourly_df`. Всегда `timezone=UTC`, `wind_speed_unit=ms`. Guard на тестовое окно для analysis-источников | по необходимости | archived_wx.py, omclient.py |
| `scada_load.py` | `load_raw(T1/T2, utc=True)` -> ts/ws/p/temp, `Etc/GMT-6 -> UTC`; `to_hourly` (label/closed=left, колонка `n`, `n<4` -> NaN, полная сетка 25 392 ч); `load_hourly_long` с `turbine_id` | нет | eda/load.py |
| `tz_check.py` | xcorr 10-мин SCADA ws vs ERA5 ws100 при лагах 3..9 ч, помесячно и pooled до/после 2024-03-01; проверка непрерывности строк вокруг 2024-03-01; вердикт. `--fetch YYYY-MM` докачивает месяцы | нет (`--fetch` — да) | eda/eda_tz2.py, verify_tz/tzverify.py, tzcheck2.py |
| `dump_single_runs.py` | 116 ранов ecmwf_ifs (2026-01-31..02-28, 00/06/12/18Z, 72 ч) -> `data/nwp_cache/single_runs_ecmwf_ifs_feb2026.csv`; пропуск, если файл есть | только при пересборке | probe9.py |
| `skill_benchmark.py` | r / RMSE / bias / r_power прогноза ветра (Previous Runs day1/day2, 5 моделей) vs SCADA ws, `--turbine T1/T2/both`, `--out csv` | нет, если кеш есть | skill.py, refute/skill_check.py |

## Данные и провенанс

Все запросы: Open-Meteo, координаты T1 `43.64515, 78.535604`, `timezone=UTC`, `wind_speed_unit=ms`, без ключа,
дата выгрузки 2026-09-23. Обе турбины (300 м друг от друга) попадают в один грид-пойнт каждой модели.

| Путь | Что | Параметры | Размер |
|---|---|---|---|
| `data/nwp_cache/single_runs_ecmwf_ifs_feb2026.csv` | 116 ранов x 72 ч ECMWF IFS 9 km, as-issued. Колонки `run_init_utc, valid_time_utc, lead_h, ws100, wd100, ws10, gust10, t2m, sp` | `single-runs-api…/v1/forecast?run=…&models=ecmwf_ifs&forecast_days=3&hourly=wind_speed_100m,wind_direction_100m,wind_speed_10m,wind_gusts_10m,temperature_2m,surface_pressure`; грид 43.620384/78.47891 | 8 352 строк, 0 null кроме `gust10` при `lead_h=0` (116) |
| `data/nwp_cache/previous_runs_feb2026/<model>.json` | Previous Runs 2026-01-31..2026-02-28, 696 ч, 8 переменных x day1/day2 (ws100/80/120/10, wd100, gusts10, t2m, sp) для `ecmwf_ifs, ecmwf_ifs025, ecmwf_aifs025_single, icon_global, gfs_global` | `previous-runs-api…/v1/forecast?start_date=2026-01-31&end_date=2026-02-28&hourly=<var>_previous_day1,<var>_previous_day2&models=<model>` | 0 null у ws100 day1/day2; `wind_gusts_10m` null у трёх ECMWF; ws80/ws120 null у ifs025/aifs |
| `data/nwp_cache/previous_runs_nov2025_jan2026/<model>.json` | То же, 2025-11-01..2026-01-31, только `wind_speed_100m` day1/day2 — окно, где есть SCADA; на нём считается skill-таблица | те же параметры, `start_date=2025-11-01&end_date=2026-01-31` | 2 208 ч, 0 null |
| `data/era5/era5_YYYY-MM.csv` (11 месяцев) | Истинный ERA5 0.25° (грид 43.75/78.5), UTC, m/s: 2023-07, 2023-12, 2024-02, 2024-04, 2025-01, 2025-02, 2025-07, 2025-10, 2025-11, 2025-12, 2026-01 | `archive-api…/v1/archive?models=era5&hourly=wind_speed_100m,wind_speed_10m,temperature_2m,wind_direction_100m,surface_pressure` (2025-11 и 2025-12 — только первые три) | проверено 1:1 против полной выгрузки `models=era5` |

Не скопировано (по правилам курирования): `hourly_T1/T2.csv` (пересоздаются `scada_load.py`), `isd-history.csv`,
`ms36894*.csv` (станция Малыбай, meteostat), JSON-выгрузки > 1 МБ (`era5_full/true`, `ifs_full`, `verify*/`),
GRIB-файл ECMWF, html-доки.

## Результаты (`research/results/`)

| Файл | Что | Откуда |
|---|---|---|
| `powercurve_T{1,2}.csv` | кривая мощности по бинам 0.5 м/с (n, median, q25, q75, mean, zero_frac), 10-мин данные, часы файла | eda_main.py |
| `gaps_T{1,2}.csv` | разрывы > 10 мин (gap_start, gap_end, dur, dur_h), часы файла; T1 67, T2 178 | eda_main.py |
| `tz_lag_10min.csv` | лаг-скан 10-мин SCADA vs ERA5 по 9 месяцам (лаг в минутах, знак инвертирован: -360 = UTC+6) | eda_tz2.py |
| `results_tz.json` | часовой xcorr и час суточного максимума температуры по сезонам | eda_tz.py |
| `results_tz2.json` | достижимый MAE мощности от ERA5-ветра (leave-one-month-out логистика), offset +6h vs +5h | eda_tz2.py |
| `results_anom.json` | залипшие датчики, простои по определениям | eda_anom.py |
| `lag_by_month.csv` | помесячный лаг по всем 35 месяцам, обе турбины. **Строки `model=ERA5` здесь = `IFS9`** (выгрузка была через `best_match`, который на этом эндпоинте отдаёт анализ IFS 9 km, не ERA5) | verify_tz/tzverify.py |
| `lag_by_month_era5true.csv` | то же на истинном ERA5 (`models=era5`, грид 43.75/78.5) — честная ERA5-версия предыдущего файла | verify_tz/tz_era5true.py |

## Ключевые факты (проверены живыми вызовами 2026-09-23)

- **Таймзона SCADA — фиксированный UTC+6** (`Etc/GMT-6`), перехода на UTC+5 в марте 2024 нет:
  25 непрерывных 10-мин строк вокруг 2024-03-01 00:00 в обоих файлах, pooled-пик xcorr ветра 6.33 ч до и 6.00 ч
  после (`tz_check.py`); на IFS 9 km — 5.83 ч во всех окнах (= 6 ч минус метка конца интервала).
  `Asia/Almaty` не использовать.
- **Previous Runs**: `<var>_previous_dayN` на час h дня D = ран D-N того же 6-часового блока, lead 24–29 ч (day1) /
  48–53 ч (day2). Проверено 1:1 против Single Runs для ecmwf_ifs. Старт архива: ifs025/icon/gfs 2024-03,
  aifs 2025-03, ecmwf_ifs 9 km 2025-10. `best_match` — никогда.
- **Single Runs**: ecmwf_ifs с 2024-03-14, `t0 == run`; остальные модели только с 2026-04-02 (для Feb 2026 — 400).
- **Historical Forecast и Archive без `models=era5`** — склейка lead 0–5 ч / анализ IFS (побайтно одинаковы).
  Не as-issued -> только train; в тестовом окне это утечка (клиент бросает `ValueError`, обход — `allow_test_window=True`).
- **Единицы**: дефолт ветра km/h; клиент форсирует m/s и падает, если пришло km/h.
- **Skill Nov 2025–Jan 2026, T1, ws100 day1** (воспроизводится `skill_benchmark.py` ±0.001):
  icon_global r 0.789 / RMSE 2.67 / bias +0.23; aifs 0.795 / 2.65 / -1.40; ecmwf_ifs 0.756 / 2.72 / -1.22;
  ifs025 0.747 / 2.91 / +1.07; gfs 0.699 / 3.50 / +1.70. Day2: aifs 0.784, icon 0.736, ecmwf_ifs 0.733,
  ifs025 0.716, gfs 0.636. SCADA ws -> p r = 0.949 (потолок). Отрицательный bias у IFS — SCADA-анемометр
  стоит за ротором и занижает ветер.
- **Лимиты free tier**: 600/мин, 5 000/ч, 10 000/день; > 10 переменных или > 2 недель на локацию = weighted-вызовы
  (`previous_runs_chunked`, 14 дней).

## Что дальше по задачам

- **LOC-8**: `scada_load.load_hourly_long()` уже даёт 25 392 ч x 2 в UTC с `n`; осталось флаги качества и parquet.
  `tz_check.py` — готовый источник для `docs/figures/tz_xcorr.png`.
- **LOC-14**: `openmeteo_client.single_run` + кеш + `dump_single_runs.py`; осталось parquet + manifest + тест семантики
  prev_day1 (данные для него: `previous_runs_feb2026/ecmwf_ifs.json` и CSV ранов).
- **LOC-15**: `previous_runs_chunked(model, "2024-03-01", "2026-02-28", vars, chunk_days=14)` по 5 моделям -> parquet;
  skill-таблица — `skill_benchmark.py --out`.

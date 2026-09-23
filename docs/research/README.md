# План фазы ресёрча

Задачи: [Hackalem AI Hackathon в Linear](https://linear.app/localhosters/project/hackalem-ai-hackathon-0db0e7dd59cc). Факты и источники: [`findings.md`](findings.md). Скрипты и кеш ресёрча: [`../../research/README.md`](../../research/README.md).

## MVP-скоуп (решение 23.09)

Фокус — один сценарий, который эксперт запускает одной командой без сети и без ключа. «Готово» = пять пунктов:

1. `make backtest` → 29 dayahead-выпусков 31.01–28.02.2026 на реальных архивных ранах ECMWF IFS → `submission/forecast_test_hourly_v0.csv` (672 ч × 2 турбины) + per-issue CSV. Модель v0 = MOS + кривая мощности — уже даёт **MAE 0.174 на январе 2026** (as-of), см. [`backtest-v0.md`](backtest-v0.md).
2. Тот же прогон идёт через агентный цикл (`get_clock → fetch_nwp → fetch_scada → check_quality → predict → compare_with_previous → save → report`) с `trace.jsonl`; scripted-режим обязателен, LLM — сверху с fallback.
3. Одна сцена пересчёта при обновлении входных данных: выпуск 31.01 18:00 UTC → 12Z становится доступен в 20:00 → DIVERGENCE → re-issue.
4. Leak-тест зелёный: `run_init + lag[cycle] ≤ issue_time` для каждой строки, падает на 19:00Z + 12Z.
5. README по чек-листу организаторов + `make verify` < 2 мин из кеша, проверен на чужой машине и в Docker.

Всё остальное — milestone **Later** (LOC-6 foundation-модели, LOC-7 Brev, LOC-19 GRIB, LOC-31 аблации/cost-aware, LOC-32 псевдо-оценка февраля; окна feb2025, market-режим, intraday-файл). Модель pluggable с первого часа: v0 живёт до конца как страховка, LightGBM v1 — улучшение через тот же контракт `predict()`.

Состояние: LOC-14 (клиент + 116 ранов) в main; LOC-16 + LOC-17 (clock, v0, бэктест, сабмиты) — [PR #2](https://github.com/BAITC-Hacks/hack-75766fed-localhosters/pull/2); LOC-8 в работе у Akylbek; runtime агента (LOC-22/23) — ветка `birrrzha/agent-foundation` (Codex).

---

## Цель фазы

Не «изучать», а превратить уже проверенные факты в решения команды и работающие спайки, из которых собирается MVP. Бюджет ~12–13 ч на человека, синки на 4-м и 11-м часу.

Главные неизвестные закрыты, верификация исправила детали: архивные прогнозы на февраль 2026 доступны без ключа (Open-Meteo Single Runs / Previous Runs — free tier, ECMWF open data на AWS), часы SCADA — фиксированный UTC+6 (вывод по pooled-окнам), раны ECMWF публичны в 07:34/12:27/19:34/00:27 UTC (константа +7 ч пропускала 12Z), площадка — ВЭС «Нурлы», GBDT на lead-aligned NWP — state of the art для горизонта 24–48 ч, рынок КЗ даёт value-историю в KZT.

Что фаза обязана выдать к Синку 2:

| Воркстрим | Артефакты |
|---|---|
| Данные и ML | `data/processed/scada_hourly.parquet` (UTC, флаги качества), `docs/figures/tz_xcorr.png` (2 панели), общий `windagent/eval/metrics.py`, таблица «честные бейзлайны / потолки», дамп Single Runs для обучения (лиды 12–59), LightGBM v1 с MAE на Jan 2026 / Feb 2025, контракт модели |
| Погода и бэктест | закоммиченный кеш 116 ранов ECMWF IFS + Previous Runs по 5 моделям с manifest, `clock.py` с per-cycle `AVAIL_LAG` и падающим leak-тестом, replay 29 issue-дней + окно feb2025 → `submission/forecast_feb2026_{dayahead,intraday,hourly}_v0.csv`, псевдо-оценка февраля по ветру |
| Агент, продукт, демо | rubric-map, прототип агента с таблицей ≥6 LLM-решений и per-issue fallback, один issue end-to-end в scripted-режиме с re-issue в 20:00 UTC и `trace.jsonl`, README-скелет с `config/sites` и `make verify` на чужой машине, дашборд v0 на реальных данных, `docs/value.md` на market-режиме |

Вне MVP (тайм-боксы, при провале → раздел «Развитие»): аблации и cost-aware квантиль (LOC-31), GRIB-адаптер (LOC-19, только при остатке после Синка 2), демо-пакет (первый кандидат в бэклог сборки). Deep-модели и платные провайдеры исключены.

---

## Что уже известно про данные

Подробности, цифры и ссылки — в [`findings.md`](findings.md).

- Площадка: **ВЭС «Нурлы» 5 МВт**, Енбекшиказахский район Алматинской области; 2 × Goldwind GW109/2500 (2.5 МВт, ротор 109 м, hub 80 м по странице оператора / 90 м по spec sheet — конфликт, уровень ветра решает LOC-31, рабочий диапазон 3–25 м/с); оператор Samruk-Green Energy (Samruk-Energo). T1 `43.645150, 78.535604`, T2 `43.643198, 78.538828`, ~338 м друг от друга; ведут себя почти одинаково.
- Два CSV (T1, T2), шаг 10 минут, период **2023-03-11 00:00 → 2026-01-31 23:50**. Колонки: время, средняя скорость ветра (м/с), нормализованная активная мощность 0..1, температура (°C). Пустых ячеек нет; мощность квантована по 0.01, floor 0.01 (ровно 0 — 534 строки T1 / 2 680 T2), cap T1 0.99, T2 0.97 до 2025Q4 и 0.99 с 2026Q1. Час = среднее ≥4 из 6 десятиминуток с меткой начала часа (`HOURLY_LABEL=left`, `MIN_SAMPLES_PER_HOUR=4`; вопрос организаторам №7).
- **Февраля 2026 в файлах нет** — скрытый тестовый период. Наши holdout: Feb 2025 (исключён из train, гоняется тем же as-of протоколом как репетиция сезона) и Jan 2026 (dev-окно с фактами).
- Таймзона — **фиксированный UTC+6 на весь файл** (проверено): pooled кросс-корреляция 10-мин SCADA-ветра с UTC `wind_speed_100m` до и после 2024-03-01 даёт пик 5.83–6.00 ч (IFS 9 км) и 6.00–6.17 ч (ERA5, `models=era5`), r@6h > r@5h в каждом окне; суточный максимум температуры SCADA в 15:00–15:30 во все сезоны; на дате перехода 25 непрерывных строк, 0 дублей. Помесячный пик плавает 5.2–6.7 ч (плато корреляции плоское ±0.5 ч, Jan 2026 vs ERA5 — 5.17 ч) — вывод делается по pooled-окнам, не по месяцам. `Asia/Almaty` (переход на UTC+5 с 2024-03-01) не использовать; `utc = t − 6h`. Archive без `models=era5` — IFS best_match, не ERA5.
- Пропуски: у T1 нет данных 2024-05-18 → 2024-07-17 (два месяца), у обеих — 2025-10-03 → 2025-10-05; всего 67 разрывов у T1 и 178 у T2. В часах (25 392 ч на турбину): пустых T1 ≈1 629, T2 ≈388. Залипший датчик 2025-05-14 12:10–15:30.
- Почасовая мощность бимодальна: 36% часов <0.1, 16% >0.9, медиана 0.24, среднее 0.37. Логистическая кривая `p = 1/(1+exp(−0.705·(ws−7.89)))` на SCADA-ветре: R² 0.962, MAE 0.031 — perfect-wind потолок при идеальном прогнозе ветра.
- Сезонность: зимой (ноябрь–март) средняя месячная мощность 0.37–0.48 (Dec 0.48, Nov/Mar 0.43, Jan 0.37), летом (июль–сентябрь) 0.26–0.33 (Jul/Aug 0.26).
- Площадка в 1.39× ветренее ERA5 `ws100` (ERA5-ветер ~1.7 м/с ниже гондолы). Bias NWP по ветру на day-1 lead (Nov 2025–Jan 2026, T1): ICON +0.2 (r 0.789; 80 м — 0.805, ближе к hub), AIFS −1.4 (0.795), IFS −1.2 (0.756), IFS025 +1.1 (0.747), GFS +1.7 (0.699) → bias-коррекция / ML поверх NWP обязательны.
- Обе турбины попадают в один грид-пойнт Open-Meteo во всех моделях (`ecmwf_ifs` 43.620384, 78.47891; DEM-высота 555 м) → NWP-ряды для T1 и T2 байт-идентичны; различают `turbine_id` и SCADA-лаги.
- Публикация ранов ECMWF IFS (open data AWS `ecmwf-forecasts`, Last-Modified всех ранов Feb 2026): 00Z 07:34, 06Z 12:27, 12Z 19:34, 18Z 00:27 UTC; Open-Meteo 9 км — ~07:00–07:15 / 12:20–12:30 / 19:00–19:15 / 00:15–00:25. Константа +7 ч не leak-safe для 00Z/12Z → `AVAIL_LAG` per-cycle {00Z: 8, 06Z: 7, 12Z: 8, 18Z: 7}. Issue 18:00 UTC D−1 → 06Z D−1 (lead 12–59); 12Z доступен только с 20:00 UTC; market 03:00 UTC D−1 → 18Z D−2 (lead 24–71, `forecast_days=4`).
- Бейзлайны (T1, issue 00:00 SCADA, h=1..48). Честные: const median 0.27 (Jan 2026) / 0.30 (Feb 2025), zero 0.31 / 0.35, климатология month×hour 0.30–0.34, same-hour-yesterday 0.37–0.40; case-compliant NWP — Previous Runs day1/day2 `ws100` (icon / ifs025) → рефит-кривая 0.20–0.22 (h1–24) / ≈0.22 (h25–48) — **число, которое надо бить**. Потолки (недоступны на момент выпуска): ERA5 через фиксированную SCADA-кривую 0.20–0.23 (bias −0.18), ERA5 рефит / MOS LOMO 0.15–0.21, perfect-wind 0.031. Цель v1: ≤0.19 (skill ≥10% vs NWP→кривая), приемлемо ≤0.22.
- Источники на Feb 2026 без ключа: Single Runs `ecmwf_ifs` — 116/116 ранов 00/06/12/18Z, 96 ч, 0 null по 6 переменным (`wind_gusts_10m` null на lead 0 → читать с lead ≥1); архив: 00Z/12Z с 2024-03-14, 06Z/18Z с 2024-08-06/07, все четыре цикла непрерывно с 2024-08-10, дыры Aug 2025 (HTTP 200 с null → полнота по null); другие модели → 400 до 2026-04-02. Previous Runs day1/day2: `icon_global` и `gfs_global` с 2024-02-16, `ecmwf_ifs025` с 2024-03-06, `ecmwf_aifs025_single` с 2025-02-18 (id `aifs` невалиден), `ecmwf_ifs` с 2025-10-01; точная provenance run_init + lead — только у hourly-native моделей (ifs025 3 ч / AIFS 6 ч — интерполяция между ранами). Historical Forecast и Archive без `models` — один и тот же stitched IFS 9 км (lead 0–5 ч с 2025-10-01, 00Z/12Z lead 1–12 до того, ранее provenance неизвестен); ERA5 — только `models=era5` (grid 43.75/78.5). Оба — только train/eval, `best_match` запрещён. Все archive-эндпоинты входят в free tier Open-Meteo (non-commercial, без SLA, 600/мин, 5 000/ч, 10 000/день, 300 000/мес) — кешировать и коммитить всё.

---

## Ключевые решения по умолчанию

Фиксируются на Синке 1; до него — рабочие дефолты. У каждого есть параметр в `config.py` / `.env.example` и строка «если иначе → что меняем» в `docs/assumptions.md`.

- **Таймзона**: фиксированный UTC+6 (`Etc/GMT-6`), `utc = t − 6h` для всего файла в одном `scada.py`, `SCADA_TZ_OFFSET_HOURS=6`; `Asia/Almaty` не использовать. Доказательство — pooled-окна до/после 2024-03-01 против IFS 9 км и ERA5 (`models=era5`) + суточный максимум температуры 15:00–15:30 + непрерывность строк; помесячный пик 5.2–6.7 ч признаётся шумом. Час = среднее ≥4 из 6 десятиминуток, метка начала часа (`HOURLY_LABEL=left`, `MIN_SAMPLES_PER_HOUR=4`; вопрос организаторам №7).
- **Доступность ранов `ecmwf_ifs`**: per-cycle, не константа — `AVAIL_LAG = {00Z: 8h, 06Z: 7h, 12Z: 8h, 18Z: 7h}` (публикация open data 07:34/12:27/19:34/00:27 UTC; Open-Meteo 9 км ~07:00–07:15 / 12:20–12:30 / 19:00–19:15 / 00:15–00:25) → допуск 08:00 / 13:00 / 20:00 / 01:00 UTC. Для Previous Runs — per-model лаги по каналу Open-Meteo: `ecmwf_ifs025` 8 ч на все циклы (в Open-Meteo 07:41 / 13:09 / 19:40 / 01:04 UTC — +7 ч пускал бы 06Z/18Z раньше публикации), `ecmwf_aifs025_single` 6 ч, `icon_global` 4 ч, `gfs_global` 7 ч (таблица — findings §3.4). Leak-тест обязан падать на issue 19:00 UTC с 12Z-раном.
- **Семантика выпусков**: официальный dayahead = issue 18:00 UTC D−1 (00:00 SCADA дня D) → ран 06Z D−1, lead 12–59 → `forecast_feb2026_dayahead.csv`; intraday re-issue (12Z в 20:00 UTC, 18Z в 01:00 UTC D, 00Z в 08:00 UTC D, 06Z в 13:00 UTC D) обновляет только `target_time > issue_time` → `forecast_feb2026_intraday.csv`; колонка `issue_kind`, `SUBMISSION_ISSUE_KIND=dayahead`. Market-режим `ISSUE_HOUR_UTC=3` (18Z D−2, lead 24–71) оценивается рядом и служит базой для KZT.
- **Источники Feb 2026**: primary — Single Runs `models=ecmwf_ifs` (`run_init_utc` + `lead_h` на каждое значение; другие модели → 400 до 2026-04-02); secondary — Previous Runs day1/day2 по `icon_global`, `ecmwf_ifs025`, `gfs_global`, `ecmwf_aifs025_single`, `ecmwf_ifs` с маской доступности; provenance «точная» только у hourly-native моделей (ifs025/AIFS — интерполяция между ранами). Historical Forecast и Archive (только `models=era5`) — train/evaluate; `best_match` (любой Archive-ответ без `models=era5`) запрещён. Весь кеш коммитится, `OPEN_METEO_CACHE_ONLY=1` — режим жюри. Всегда `timezone=UTC&wind_speed_unit=ms`.
- **Модель MVP**: pooled LightGBM (`turbine_id`) на признаках Single Runs `ecmwf_ifs` с теми же лидами 12–59 (дамп 2024-03-14→2026-01-31, 06Z; до 2024-08-09 — 00Z, fallback по факту 400 / all-null, не по дате) + Previous Runs других моделей как вторичные; train 2024-03→2025-12 без Feb 2025, holdout Feb 2025 + Jan 2026; `scada_age_h` и маскирование лагов; цель MAE ≤0.19 (skill ≥10% vs NWP→кривая), приемлемо ≤0.22; v0 = MOS + логистика как страховка. Deep-модели — нет.
- **Бейзлайны разделены**: честные (median 0.27/0.30, климатология 0.30–0.34, same-hour-yesterday 0.37–0.40, Previous Runs `ws100` → рефит-кривая 0.20–0.22 h1–24 / ≈0.22 h25–48 — «число, которое надо бить») и потолки, недоступные на момент выпуска (ERA5 фикс. кривая 0.20–0.23, ERA5 рефит/MOS 0.15–0.21, perfect-wind 0.031).
- **Точечная оценка**: P50 если MAE, mean если RMSE, cost-optimal квантиль как опция `POINT_ESTIMATE`; P10/P90 отдаём всегда. Очистка — флагами, train on clean / evaluate on all, двойная таблица метрик.
- **Формат выхода**: per-issue CSV (29 × 48 × 2 = 2 784 строк: `issue_time_utc/scada, target_time_scada/utc, turbine, lead_h, nwp_run_init_utc, issue_kind, p10/p50/p90, outside_test_period`) + плоский hourly CSV (672 ч × 2 турбины: `p50_h1_24, p50_h25_48, p10, p90`, provenance) + `plant_mw` / `energy_mwh`; часы SCADA + колонка UTC.
- **Агент**: Pydantic AI vs bare Anthropic tool runner — решить за 30 мин; `LLM_MODE=auto|anthropic|scripted` с per-issue fallback и `fallback_reason` в trace; `temperature=0`, `model_id`, `prompt_sha256`, `usage` в каждом шаге; ≥6 именованных LLM-решений (quality gate, выбор источника, bias-correction, re-issue при DIVERGENCE, no_lags при `scada_age_h>6`, отчёт + memory), у каждого scripted-правило. LangGraph / CrewAI / Claude Agent SDK — нет.
- **«Анализ → пересчёт»**: dev-окно Jan 2026 (факты: evaluate / drift / residual alert) + feb2025 (репетиция сезона) + test Feb 2026 (только `NWP_RUN` / `DIVERGENCE`), одна команда `make backtest`; псевдо-оценка февраля по ветру против near-analysis.
- **Площадка — сущность**: `config/sites/nurly.yaml` (turbines, hub_m, rated_mw, tz_offset_hours), `SITE=nurly`, все tools принимают `site_id`; второй yaml без SCADA проходит fetch / `check_data_quality` — доказательство масштабирования.
- **Лицензии**: Open-Meteo free tier включает archive-API, но только non-commercial и без SLA (600/мин, 5 000/ч, 10 000/день, 300 000/мес) → кеш коммитим; для промышленной эксплуатации — подписка или self-host (S3 `openmeteo` / сырой ECMWF).

---

## Воркстримы

Приоритет: 1 — без этого нет MVP, 2 — нужно к Синку 2, 3–4 — тайм-бокс, при провале → «Развитие». Описания, критерии готовности и чек-листы — в Linear, здесь по строке на задачу.

Критический путь: LOC-15 → LOC-18 → LOC-10 → LOC-11 → LOC-12 → Синк 2 (`om_get` в первые 30 мин, parquet Previous Runs нужен Akylbek к 2.5-му часу) и LOC-15 → LOC-14 → LOC-23 → LOC-26 → Синк 2; LOC-17 (после LOC-14, LOC-16, LOC-8, LOC-9) → LOC-26. Порядок Ramazan: `om_get` → Previous Runs → Single Runs Feb 2026 → Синк 1; код `clock.py` — после Синка 1.

### Данные и ML-модель — Akylbek

Цель: один parquet в UTC с флагами и двухпанельным tz-доказательством, `metrics.py` и таблица «честные бейзлайны / потолки», дамп Single Runs `ecmwf_ifs` для обучения на лидах 12–59, LightGBM v1 с MAE ≤0.19–0.22 на Jan 2026 и Feb 2025, квантили, контракт модели с тестом train == inference.

| Linear | Задача | P | ч | Зависит от |
|---|---|---|---|---|
| [LOC-8](https://linear.app/localhosters/issue/LOC-8) | Собрать hourly-датасет SCADA в UTC с флагами качества и tz-доказательством | 1 | 2 | — |
| [LOC-9](https://linear.app/localhosters/issue/LOC-9) | `metrics.py` и таблица «честные бейзлайны / потолки» (Feb 2024, Feb 2025, Jan 2026) | 1 | 1.5 | LOC-8 |
| [LOC-18](https://linear.app/localhosters/issue/LOC-18) | Дамп Single Runs `ecmwf_ifs` 2024-03-14→2026-01-31 для обучения на лидах 12–59 | 1 | 1.5 | LOC-15 |
| [LOC-10](https://linear.app/localhosters/issue/LOC-10) | Спайк: LightGBM v1 на lead-aligned признаках Single Runs + Previous Runs | 1 | 3.5 | LOC-8, LOC-18, LOC-15 |
| [LOC-11](https://linear.app/localhosters/issue/LOC-11) | Квантили P10/P50/P90 и выбор точечной оценки под метрику | 2 | 1.5 | LOC-10 |
| [LOC-12](https://linear.app/localhosters/issue/LOC-12) | Контракт модели: `FEATURES`, `build_features()`, `metadata.json`, `predict()` | 2 | 1 | LOC-10, LOC-11 |
| [LOC-31](https://linear.app/localhosters/issue/LOC-31) | Тайм-бокс: аблации (HF pre-train, уровень ветра, recency) и cost-aware `expected_cost()` | 3 | 2 | LOC-11 |
| [LOC-6](https://linear.app/localhosters/issue/LOC-6) | Foundation-модели временных рядов (Chronos / TimesFM) на холдауте | 3 | 3 | LOC-8 |

Итого 13 ч (P1–P2: 11 ч). LOC-13 (cost-aware) объединена с LOC-31. LOC-6 (3 ч) — вне бюджета и вне MVP (решение «Deep-модели — нет»): только если v1 готова раньше срока, как аблация.

### Погодные данные и бэктест — Ramazan

Цель: `om_get` с кешом (первые 30 мин), дамп Previous Runs по 5 моделям (Akylbek к 2.5 ч), кеш 116 ранов `ecmwf_ifs` Feb 2026 с manifest, as-of конвенция с per-cycle `Clock` и падающим leak-тестом, replay 29 дней + окно Feb 2025 + плоский hourly CSV → submission v0, псевдо-оценка февраля по ветру.

| Linear | Задача | P | ч | Зависит от |
|---|---|---|---|---|
| [LOC-15](https://linear.app/localhosters/issue/LOC-15) | Клиент Open-Meteo `om_get` с кешом + дамп Previous Runs (5 моделей) | 1 | 2.5 | — |
| [LOC-14](https://linear.app/localhosters/issue/LOC-14) | Дамп Single Runs `ecmwf_ifs`: 116 ранов 31.01–28.02.2026 + manifest + тест семантики | 1 | 1.5 | LOC-15 |
| [LOC-16](https://linear.app/localhosters/issue/LOC-16) | As-of конвенция: документ к Синку 1, затем `clock.py` с per-cycle `AVAIL_LAG` и leak-тест | 1 | 2 | — |
| [LOC-17](https://linear.app/localhosters/issue/LOC-17) | Скелет as-of бэктеста: replay 29 дней, submission v0 (per-issue + hourly), окна dev/feb2025, market-режим | 1 | 3 | LOC-14, LOC-16, LOC-8, LOC-9 |
| [LOC-32](https://linear.app/localhosters/issue/LOC-32) | Псевдо-оценка Feb 2026 на уровне ветра (as-of vs near-analysis) | 2 | 1 | LOC-14, LOC-16 |
| [LOC-20](https://linear.app/localhosters/issue/LOC-20) | Live-режим `fetch_live()` в схеме `single_run()` + офлайн-режим, лимиты и attribution | 3 | 1 | LOC-14 |
| [LOC-19](https://linear.app/localhosters/issue/LOC-19) | Спайк (только при остатке после Синка 2): GRIB-адаптер ECMWF AWS как 2-й источник | 4 | 1.5 | LOC-30 |

Итого 11 ч (P1: 9 ч, P1–P2: 10 ч) + 1.5 ч GRIB только при остатке после Синка 2.

### Агент, продукт, README, демо — Birzhan

Цель: rubric-map и допущения с параметрами, выбранный фреймворк с ≥6 LLM-решениями и контрактами tools, один issue end-to-end в scripted-режиме с re-issue в 20:00 UTC и `trace.jsonl`, README-скелет с site-конфигом и `make verify` на чужой машине, дашборд на реальных данных v0, `docs/value.md` на market-режиме.

| Linear | Задача | P | ч | Зависит от |
|---|---|---|---|---|
| [LOC-21](https://linear.app/localhosters/issue/LOC-21) | Собрать rubric-map и `docs/assumptions.md` с дефолтами «если иначе» | 1 | 1 | — |
| [LOC-22](https://linear.app/localhosters/issue/LOC-22) | Решить фреймворк агента: прототип, ≥6 LLM-решений, контракты tools, fallback, цена | 1 | 2 | — |
| [LOC-23](https://linear.app/localhosters/issue/LOC-23) | Спайк: один issue end-to-end в scripted-режиме → `trace.jsonl` + `report.md` (re-issue в 20:00 UTC) | 1 | 3 | LOC-22, LOC-14 |
| [LOC-24](https://linear.app/localhosters/issue/LOC-24) | Определить триггеры пересчёта и окна dev/feb2025/test (актуалы февраля скрыты) | 2 | 1 | LOC-22 |
| [LOC-25](https://linear.app/localhosters/issue/LOC-25) | README-скелет + `.env.example` + Makefile + Dockerfile + `config/sites` + `make verify` | 1 | 2 | — |
| [LOC-26](https://linear.app/localhosters/issue/LOC-26) | Дашборд-макет на реальных данных v0: прогноз vs факт, ревизии, трейс | 2 | 2.5 | LOC-17, LOC-23 |
| [LOC-27](https://linear.app/localhosters/issue/LOC-27) | Питч: `docs/value.md` на market-режиме (KZT) + демо-пакет (слайды, запись, FAQ, офлайн) | 3 | 2 | LOC-9, LOC-17 |
| [LOC-7](https://linear.app/localhosters/issue/LOC-7) | Поднять Brev-инстанс как общий dev-box и проверить проброс порта | 2 | 1.5 | — |

Итого 13.5 ч (P1–P2: 11.5 ч) + LOC-28 0.5 ч. LOC-7 (1.5 ч) — инфраструктура, вне бюджета. Демо-пакет из LOC-27 (1 ч) — первый кандидат в бэклог сборки.

### Бюджет часов

| Кто | Воркстрим | из них P1–P2 | Синки (LOC-29 + LOC-30) | Всего |
|---|---|---|---|---|
| Akylbek | 13 | 11 | 2.5 | 15.5 |
| Ramazan | 11 (+1.5 GRIB при остатке) | 10 | 2.5 | 13.5 |
| Birzhan | 13.5 | 11.5 | 2.5 + 0.5 (LOC-28) | 16.5 |

Бюджет фазы ~12–13 ч на человека → P3–P4 задачи (Akylbek 2 ч, Ramazan 1 ч + GRIB 1.5 ч, Birzhan 2 ч) — тайм-боксы, режутся первыми; демо-пакет и `runs/llm/` уходят в бэклог сборки с явной датой. LOC-6 и LOC-7 в бюджет не входят.

---

## Общие точки синхронизации

| Linear | Что | Когда | Кто | ч | Зависит от |
|---|---|---|---|---|---|
| [LOC-28](https://linear.app/localhosters/issue/LOC-28) | Вопросы по условию — закрыты решениями команды 23.09, организаторам не отправляли ([questions.md](questions.md)) | — | Birzhan | 0.5 | — |
| [LOC-29](https://linear.app/localhosters/issue/LOC-29) | Синк 1 | ≈4-й час, 30 мин | все | 0.5 | LOC-8, LOC-15, LOC-16, LOC-21 |
| [LOC-30](https://linear.app/localhosters/issue/LOC-30) | Синк 2 | ≈11-й час, 2 ч | все | 2 | LOC-12, LOC-17, LOC-23, LOC-26 |

**LOC-28 — вопросы по условию.** Закрыты командой 23.09 без запроса организаторам: MAE и RMSE по турбинам, метки в часах SCADA (UTC+6) + UTC, выпуск 18:00 UTC = 00:00 SCADA на 48 ч, сабмит — почасовой ряд 672 ч × 2 турбины + файл по выпускам + сумма ВЭС в МВт·ч, Open-Meteo Single Runs как открытый источник, час = среднее ≥4 из 6 десятиминуток с меткой начала. Обоснования — [questions.md](questions.md), план отката — [assumptions.md](../assumptions.md).

**LOC-29 — Синк 1.** После него ни один спайк не меняет схему времени, источников и формата; зависимости сокращены до того, что реально готово к 4-му часу (код `clock.py` — после синка). Решаем: UTC+6 фикс (pooled png Akylbek); primary Single Runs `ecmwf_ifs` + secondary Previous Runs 5 моделей с маской; Historical Forecast / ERA5 — только train; `best_match` / Archive без `models=era5` запрещены; per-cycle `AVAIL_LAG` (+8/+7/+8/+7) → dayahead 18:00 UTC D−1 = 06Z, re-issue 12Z в 20:00 UTC; `SUBMISSION_ISSUE_KIND=dayahead`, `ISSUE_HOUR_UTC`; 29 issue-дней, колонки per-issue и hourly CSV; holdout Feb 2025 + Jan 2026 (Feb 2025 вне train); train на дампе Single Runs (go/no-go Akylbek); point = P50; rubric-map — кто что доказывает; 2–3 фичи оригинальности. Выход: `docs/research/decisions.md` (≥10 строк «решение / кто / почему»), константы `SCADA_TZ_OFFSET_HOURS`, `ISSUE_HOUR_UTC`, `AVAIL_LAG`, `SUBMISSION_ISSUE_KIND`, `HOURLY_LABEL` в одном `config.py`; Ramazan и Akylbek подтверждают, что parquet-схемы (SCADA, Previous Runs, Single Runs) совпадают.

**LOC-30 — Синк 2.** Конец фазы = зелёный прогон 29 issue-дней на реальных данных с моделью v1 в scripted-режиме на трёх окнах — это и есть MVP. Делаем: `predict()` из контракта модели → `predict_power`, кеш Single Runs → `fetch_nwp_forecast`, `Clock` → `get_clock`, `metrics.py` → `evaluate_forecast`; `python -m windagent backtest --window test|dev|feb2025 --llm scripted`; `scripts/flatten_submission.py`; `make verify` на чужой машине; смотрим дашборд; проходим rubric-map по статусам; составляем бэклог сборки в Linear (milestone «Build») с владельцами, оценками и порядком «что режем при нехватке времени»: GRIB → cost-aware → аблации → фичи дашборда; демо-пакет и `runs/llm/` (3 дня LLM-трейсов) — с явной датой. Выход: `submission/forecast_feb2026_dayahead_v1.csv` + `…_hourly_v1.csv` (2 784 + 672 × 2 строк), MAE Jan 2026 и Feb 2025 (as-of) ≤0.22 (цель ≤0.19) в README «Результаты», `test_clock_no_leakage.py`, `test_feature_schema.py`, `test_prev_day_semantics.py` зелёные, у каждой build-задачи владелец, оценка и ссылка на артефакт ресёрча. Hard stop.

---

## Риски и меры

| Риск | Мера |
|---|---|
| Жюри оспорит «архивность»: раны ECMWF публичны в 07:34/12:27/19:34/00:27 UTC; константа +7 ч пропускала 12Z в 19:00; `previous_dayN` смешивает четыре рана дня D−N, часть публикуется после полуночи | Per-cycle `AVAIL_LAG` (+8/+7/+8/+7) в `Clock`; primary — Single Runs с явным `run_init_utc` и `lead_h`; re-issue 12Z только с 20:00 UTC; unit-тест, падающий на 19:00Z + 12Z и на analysis-источниках в predict-пути; таблица «ран → канал → время публикации» в README; `previous_dayN` только через маску доступности |
| Семантика выпусков: пересчитанный в 02:00 SCADA 1 февраля прогноз могут не засчитать как «прогноз на 31 января»; организаторы могут ждать один ряд на час, сумму ВЭС или МВт·ч | Официальный сабмит = dayahead (06Z D−1), intraday — отдельный файл и revision plot; `issue_kind` во всех CSV; плоский hourly CSV с `plant_mw` / `energy_mwh`; вопросы №3, №4, №7 организаторам в первый час; параметры `SUBMISSION_ISSUE_KIND`, `HOURLY_LABEL`, `POINT_ESTIMATE` |
| Train/serve mismatch: обучение на Previous Runs (lead 24–53, архив `ecmwf_ifs` только с 2025-10) при инференсе на Single Runs 06Z (lead 12–59); лаги SCADA в test-окне устаревают до 28 дней | Дамп Single Runs для обучения 2024-03-14→2026-01-31 — P1 у Akylbek (LOC-18); признаки `lead_h` / `run_cycle`; Previous Runs — вторичные с той же маской в train и test; `scada_age_h` и маскирование лагов в train; тест покрытия `lead_h` 12–59; go/no-go с fallback на Previous Runs |
| Актуалы Feb 2026 скрыты — триггеры «анализ → пересчёт» нельзя показать на тестовом окне; ошибка сдвига/единиц на самом феврале останется незамеченной | Dev-окно Jan 2026 и feb2025 (репетиция сезона) с фактами; test-окно с `NWP_RUN` / `DIVERGENCE`; псевдо-оценка февраля по ветру vs near-analysis (LOC-32); всё в одной команде `make backtest`; трейсы закоммичены |
| LightGBM v1 не побьёт case-compliant бейзлайн NWP→кривая (0.20–0.22): мало lead-aligned данных, Feb 2025 вне train | Цель ≤0.19 / приемлемо ≤0.22; v0 = MOS + логистика в скелете бэктеста как страховочный submission к ~8-му часу; NaN-признаки для моделей с коротким архивом; HF pre-train как аблация с оговоркой о смене lead-структуры |
| Ошибка таймзоны/единиц: Open-Meteo по умолчанию km/h; помесячный tz-пик плавает 5.2–6.7 ч и один выпадающий месяц подорвёт доказательство | Всегда `timezone=UTC&wind_speed_unit=ms`; фиксированный −6 ч в одном `scada.py`; `tz_check` на pooled-окнах против IFS 9 км и ERA5 (`models=era5`) + панель суточного максимума температуры; запрет Archive без `models=era5`; честная фраза в README о помесячном разбросе |
| Open-Meteo free tier — non-commercial, без гарантии аптайма, лимиты 600/мин, 10 000/день, 300 000/мес; HTTP 200 с null-ранами (Aug 2025), gusts null на lead 0, невалидный id `aifs` | Кешировать и коммитить все raw JSON + manifest с `n_null` в первые 2 часа; `OPEN_METEO_CACHE_ONLY=1` как режим жюри; резать запросы по 2 недели; полнота по null; gusts с lead ≥1; корректные model id; лицензионная оговорка в README; GRIB-адаптер только при остатке времени |
| У экспертов нет `ANTHROPIC_API_KEY` или сети; LLM-режим падает на середине replay или трейс невоспроизводим | `LLM_MODE=auto` с per-issue fallback в scripted и `fallback_reason`; `temperature=0`, `model_id`, `prompt_sha256`, `usage` в trace; `make verify` <2 мин офлайн на чужой машине и в Docker; `runs/llm/` с 3 днями реальных трейсов; `TestModel` в pytest; `make check-secrets` |
| Ramazan — единственная точка отказа с P1-задачами до Синка 1; Akylbek блокируется на parquet; ресёрч расползается (GRIB, cost-aware, аблации, демо-пакет) | Порядок Ramazan: `om_get` (30 мин) → Previous Runs (Akylbek к 2.5 ч) → Single Runs Feb 2026 → Синк 1; код `Clock` после Синка 1; дамп для обучения у Akylbek; Birzhan в часы 6–9 закрывает README и заготовку дашборда на фикстуре; P3/P4 с тайм-боксами; Синк 2 — hard stop с порядком «что режем» |

---

## Что дальше

После Синка 2 начинается фаза сборки (milestone «Build» в Linear). Вход в неё: `submission/forecast_feb2026_dayahead_v1.csv` + `…_hourly_v1.csv`, зелёные leak-, schema- и semantics-тесты, `make verify` на чужой машине, бэклог с владельцами и оценками, каждая задача ссылается на артефакт ресёрча.

Порядок сборки: LLM-планировщик поверх scripted (те же ≥6 решений, `LLM_MODE=auto`, `runs/llm/` с 3 днями трейсов) → дашборд по `docs/demo-storyboard.md` → README по чек-листу организаторов → демо-пакет → раздел «Развитие» из тайм-боксов, которые не закрылись. Что режем при нехватке времени: GRIB → cost-aware → аблации → фичи дашборда.

# План фазы ресёрча

Задачи: [Hackalem AI Hackathon в Linear](https://linear.app/localhosters/project/hackalem-ai-hackathon-0db0e7dd59cc). Факты и источники: [`findings.md`](findings.md). Скрипты и кеш ресёрча: [`../../research/README.md`](../../research/README.md).

## Цель фазы

Не «изучать», а превратить уже проверенные факты в решения команды и работающие спайки, из которых собирается MVP. Бюджет ~12 ч на человека, синки на 4-м и 11-м часу.

Главные неизвестные закрыты: архивные прогнозы на февраль 2026 доступны бесплатно (Open-Meteo Single Runs / Previous Runs, ECMWF open data на AWS), часы SCADA — фиксированный UTC+6, площадка — ВЭС «Нурлы», GBDT на NWP — state of the art для горизонта 24–48 ч, рынок КЗ даёт value-историю в KZT.

Что фаза обязана выдать к Синку 2:

| Воркстрим | Артефакты |
|---|---|
| Данные и ML | `data/processed/scada_hourly.parquet` (UTC, флаги качества), `docs/figures/tz_xcorr.png`, общий `windagent/eval/metrics.py`, таблица бейзлайнов, LightGBM v1 с MAE на Jan 2026 / Feb 2025, контракт модели |
| Погода и бэктест | закоммиченный кеш 116 ранов ECMWF IFS + Previous Runs по 5 моделям с manifest, `clock.py` с leak-тестом, replay 29 issue-дней → `submission/forecast_feb2026_v0.csv` |
| Агент, продукт, демо | rubric-map, прототип агента с таблицей ≥5 LLM-решений, один issue end-to-end в scripted-режиме с `trace.jsonl`, README-скелет с `make verify` на чужой машине, дашборд v0 на реальных данных, `docs/value.md` |

Вне MVP (тайм-боксы, при провале → раздел «Развитие»): GRIB-адаптер, cost-aware квантиль, дамп Single Runs для обучения. Deep-модели и платные провайдеры исключены.

---

## Что уже известно про данные

Подробности, цифры и ссылки — в [`findings.md`](findings.md).

- Площадка: **ВЭС «Нурлы» 5 МВт**, Енбекшиказахский район Алматинской области; 2 × Goldwind GW109/2500 (2.5 МВт, ротор 109 м, hub 80 м по странице оператора / 90 м по spec sheet — конфликт, уровень ветра решает LOC-31, рабочий диапазон 3–25 м/с); оператор Samruk-Green Energy (Samruk-Energo). T1 `43.645150, 78.535604`, T2 `43.643198, 78.538828`, ~338 м друг от друга; ведут себя почти одинаково.
- Два CSV (T1, T2), шаг 10 минут, период **2023-03-11 00:00 → 2026-01-31 23:50**. Колонки: время, средняя скорость ветра (м/с), нормализованная активная мощность 0..1, температура (°C). Пустых ячеек нет; мощность квантована по 0.01, floor 0.01 (ровно 0 — 534 строки T1 / 2 680 T2), cap T1 0.99, T2 0.97 до 2025Q4 и 0.99 с 2026Q1.
- **Февраля 2026 в файлах нет** — скрытый тестовый период. Наши holdout: Feb 2025 (исключён из train) и Jan 2026 (dev-окно с фактами).
- Таймзона — **фиксированный UTC+6 на весь файл** (проверено): кросс-корреляция SCADA-ветра с ERA5/IFS `wind_speed_100m` даёт пик +5.7…+6.5 ч в каждом окне до и после 2024-03-01, на дате перехода нет пропущенной или дублированной строки; единственная неоднозначность — Jan 2026 по ветру даёт −5.0…−5.5 ч, температура и суточный пик по-прежнему +6. `Asia/Almaty` (переход на UTC+5 с 2024-03-01) не использовать; `utc = t − 6h`.
- Пропуски: у T1 нет данных 2024-05-18 → 2024-07-17 (два месяца), у обеих — 2025-10-03 → 2025-10-05; всего 67 разрывов у T1 и 178 у T2. В часах (25 392 ч на турбину): пустых T1 ≈1 629, T2 ≈388. Залипший датчик 2025-05-14 12:10–15:30.
- Почасовая мощность бимодальна: 36% часов <0.1, 16% >0.9, медиана 0.24, среднее 0.37. Логистическая кривая `p = 1/(1+exp(−0.705·(ws−7.89)))` на SCADA-ветре: R² 0.96, MAE 0.03 — потолок точности при идеальном прогнозе ветра.
- Сезонность: зимой (ноябрь–март) средняя месячная мощность 0.37–0.48 (Dec 0.48, Nov/Mar 0.43, Jan 0.37), летом (июль–сентябрь) 0.26–0.33 (Jul/Aug 0.26).
- Площадка в 1.39× ветренее ERA5 `ws100` (ветровой коридор). Bias NWP по ветру на day-1 lead: IFS −1.2 м/с, ICON +0.2, GFS +1.7 → bias-коррекция / ML поверх NWP обязательны.
- Обе турбины попадают в один грид-пойнт Open-Meteo (43.620384, 78.47891, 555 м) → NWP-признаки для T1 и T2 одинаковы; различают `turbine_id` и SCADA-лаги.
- Бейзлайны (T1, issue 00:00 SCADA, h=1..48): const median MAE ≈0.27 (Jan 2026) / 0.31 (Feb 2025), same-hour-yesterday 0.37–0.40, ERA5-ветер через кривую 0.17–0.21. Цель v1: ≤0.22, приемлемо ≤0.25.
- Источники на Feb 2026 без ключа: Single Runs `ecmwf_ifs` — 116 ранов 00/06/12/18Z (архив с 2024-03-14); Previous Runs day1/day2 по `icon_global`, `ecmwf_ifs025`, `gfs_global` (с 2024-03-15), `ecmwf_aifs025_single` (с 2025-03), `ecmwf_ifs` (с 2025-10). Historical Forecast (сшивка lead 0–5 ч; Archive без `models` отдаёт то же самое, не ERA5) и Archive `models=era5` (реанализ) — только для train/eval. Archive-эндпоинты помечены Professional — кешировать всё.

---

## Ключевые решения по умолчанию

Фиксируются на Синке 1; до него — рабочие дефолты. У каждого есть параметр в `config.py` / `.env.example` и строка «если иначе → что меняем» в `docs/assumptions.md`.

- **Таймзона**: `SCADA_TZ_OFFSET_HOURS=6`, `tz_localize('Etc/GMT-6')` в одном `scada.py`. Submission — в часах SCADA + колонка UTC. Доказательство — `docs/figures/tz_xcorr.png`.
- **As-of конвенция**: `issue_time = D−1 18:00 UTC` (= 00:00 дня D по SCADA); ран доступен при `run_init + 7h ≤ issue_time` → primary 06Z D−1 (lead 12–59 ч); 12Z публикуется ~18:30 UTC → автоматический re-issue в 19:00 UTC (= «повторный расчёт при обновлении»). Market-режим `ISSUE_HOUR_UTC=3` (08:00 Astana, ран 18Z D−2, lead 24–71). 29 issue-дней 31.01–28.02, горизонт 48 ч с 00:00 D+1 SCADA.
- **Источники Feb 2026**: primary — Single Runs `ecmwf_ifs` (`run_init_utc` + `lead_h` на каждое значение); secondary — Previous Runs day1/day2 по 5 моделям с маской доступности. Historical Forecast / Archive `era5` — только train/eval; `best_match` запрещён. Весь кеш коммитится; `OPEN_METEO_CACHE_ONLY=1` — режим для жюри. Всегда `timezone=UTC&wind_speed_unit=ms` (дефолт — km/h и `timezone=auto`).
- **Модель MVP**: pooled LightGBM (`turbine_id` categorical) на lead-aligned признаках Previous Runs day1/day2; train 2024-03→2025-12 без Feb 2025; holdout Feb 2025 + Jan 2026. v0 = линейный MOS + логистическая кривая как страховочный submission. Deep-модели — нет.
- **Точечная оценка**: `POINT_ESTIMATE=median` если скорят MAE, `mean` если RMSE, `cost` как опция; P10/P90 отдаём всегда.
- **Очистка**: флаги колонками (`range, frozen, outage, curve_resid, curtail, icing, t1_outage`), не удалением; train on clean / evaluate on all; двойная таблица метрик (raw / weather-explainable).
- **Фреймворк агента**: Pydantic AI vs bare Anthropic tool runner — решить за 30 мин на стенде; `LLM_MODE=scripted` обязателен как путь для жюри без ключа; ≥5 именованных LLM-решений, у каждого scripted-правило и поле в `trace.jsonl`. LangGraph / CrewAI / Claude Agent SDK — нет.
- **«Анализ → пересчёт»**: dev-окно Jan 2026 (есть факты: evaluate / drift / residual alert) + test-окно Feb 2026 (только триггеры `NWP_RUN` и `DIVERGENCE`); одна команда `make backtest`.
- **Submission CSV**: `issue_time_utc, issue_time_scada, target_time_scada, target_time_utc, turbine, lead_h, nwp_run_init_utc, p10, p50, p90, outside_test_period`; per turbine, 29 × 48 × 2 = 2 784 строки.
- **Дашборд**: static Vite/React поверх `runs/*.csv` + `trace.jsonl`, без бэкенда, dark-first, muted-палитра. Оригинальность: per-hour provenance, cost-aware квантиль под правила небаланса КЗ, GRIB-адаптер ECMWF AWS (тайм-боксы).

---

## Воркстримы

Приоритет: 1 — без этого нет MVP, 2 — нужно к Синку 2, 3–4 — тайм-бокс, при провале → «Развитие». Описания, критерии готовности и чек-листы — в Linear, здесь по строке на задачу.

Критический путь: LOC-15 → LOC-10 → LOC-11 → LOC-12 → Синк 2 (parquet Previous Runs нужен Akylbek к 4-му часу) и LOC-14 → LOC-23 → LOC-26 → Синк 2.

### Данные и ML-модель — Akylbek

Цель: один parquet в UTC с флагами и png-доказательством таймзоны, общий `metrics.py` и таблица бейзлайнов / потолка, LightGBM v1 с MAE ≤0.22–0.25 на Jan 2026 и Feb 2025, квантили, контракт модели с тестом train == inference.

| Linear | Задача | P | ч | Зависит от |
|---|---|---|---|---|
| [LOC-8](https://linear.app/localhosters/issue/LOC-8) | Hourly-датасет SCADA в UTC с флагами качества и tz-доказательством | 1 | 2 | — |
| [LOC-9](https://linear.app/localhosters/issue/LOC-9) | Общий `metrics.py` и таблица бейзлайнов (Feb 2024, Feb 2025, Jan 2026) | 1 | 1.5 | LOC-8 |
| [LOC-10](https://linear.app/localhosters/issue/LOC-10) | Спайк: LightGBM v1 на lead-aligned признаках Previous Runs day1/day2 | 1 | 3.5 | LOC-8, LOC-15 |
| [LOC-11](https://linear.app/localhosters/issue/LOC-11) | Квантили P10/P50/P90 и выбор точечной оценки под метрику | 2 | 1.5 | LOC-10 |
| [LOC-12](https://linear.app/localhosters/issue/LOC-12) | Контракт модели: `FEATURES`, `build_features()`, `metadata.json`, `predict()` | 2 | 1 | LOC-10, LOC-11 |
| [LOC-31](https://linear.app/localhosters/issue/LOC-31) | Аблации: HF pre-train, уровень ветра 80/100/120 м, recency-веса | 3 | 1.5 | LOC-10 |
| [LOC-13](https://linear.app/localhosters/issue/LOC-13) | Cost-aware точка прогноза: `expected_cost()` по правилам небаланса КЗ | 4 | 1 | LOC-11 |
| [LOC-6](https://linear.app/localhosters/issue/LOC-6) | Foundation-модели временных рядов (Chronos / TimesFM) на холдауте | 3 | — | LOC-8, LOC-9 |

Итого 12 ч (P1–P2: 9.5 ч). LOC-6 — вне плана, без оценки: только если v1 готова раньше срока.

### Погодные данные и бэктест — Ramazan

Цель: закоммиченный кеш 116 ранов ECMWF IFS за 31.01–28.02.2026 и дамп Previous Runs по 5 моделям с manifest, as-of конвенция с `Clock` и leak-тестом (включая запрет analysis-источников), прогон 29 issue-дней с моделью v0 → submission v0 и MAE на dev-окне Jan 2026.

| Linear | Задача | P | ч | Зависит от |
|---|---|---|---|---|
| [LOC-14](https://linear.app/localhosters/issue/LOC-14) | Клиент Open-Meteo с кешом + дамп Single Runs `ecmwf_ifs` за 31.01–28.02.2026 | 1 | 2 | — |
| [LOC-15](https://linear.app/localhosters/issue/LOC-15) | Дамп Previous Runs day1/day2 (5 моделей) 2024-03→2026-02 + skill-таблица | 1 | 2 | — |
| [LOC-16](https://linear.app/localhosters/issue/LOC-16) | As-of конвенция: `Clock`, `allowed_runs`, leak-тест | 1 | 2 | — |
| [LOC-17](https://linear.app/localhosters/issue/LOC-17) | Скелет as-of бэктеста: replay 29 дней + submission v0 (MOS + кривая) | 1 | 3 | LOC-14, LOC-16, LOC-8, LOC-9 |
| [LOC-18](https://linear.app/localhosters/issue/LOC-18) | Go/no-go: дамп Single Runs `ecmwf_ifs` 2024-03-14→2026-01-31 для обучения | 3 | 1 | LOC-14, LOC-16 |
| [LOC-19](https://linear.app/localhosters/issue/LOC-19) | Спайк: raw ECMWF GRIB adapter (AWS byte-range + cfgrib) как 2-й источник | 3 | 1.5 | LOC-14 |
| [LOC-20](https://linear.app/localhosters/issue/LOC-20) | Live-режим `fetch_live()` в схеме `single_run()` + offline-режим и attribution | 3 | 1 | LOC-14 |

Итого 12.5 ч (P1: 9 ч).

### Агент, продукт, README, демо — Birzhan

Цель: rubric-map и допущения, выбранный фреймворк с таблицей ≥5 LLM-решений и контрактами tools, один issue end-to-end в scripted-режиме с `trace.jsonl`, README-скелет по чек-листу с `make verify` на чужой машине и Docker, дашборд-макет на реальных данных v0, питч с числами и `docs/value.md`.

| Linear | Задача | P | ч | Зависит от |
|---|---|---|---|---|
| [LOC-21](https://linear.app/localhosters/issue/LOC-21) | Rubric-map и `docs/assumptions.md` с дефолтами «если иначе» | 1 | 1 | — |
| [LOC-22](https://linear.app/localhosters/issue/LOC-22) | Фреймворк агента: прототип, ≥5 LLM-решений, контракты tools, цена | 1 | 2 | — |
| [LOC-23](https://linear.app/localhosters/issue/LOC-23) | Спайк: один issue end-to-end в scripted-режиме → `trace.jsonl` + `report.md` | 1 | 3 | LOC-22, LOC-14 |
| [LOC-24](https://linear.app/localhosters/issue/LOC-24) | Триггеры пересчёта и окна dev/test (актуалы февраля скрыты) | 2 | 1 | LOC-22 |
| [LOC-25](https://linear.app/localhosters/issue/LOC-25) | README-скелет по чек-листу + `.env.example` + Makefile + Dockerfile + `make verify` | 1 | 2 | — |
| [LOC-26](https://linear.app/localhosters/issue/LOC-26) | Дашборд-макет на реальных данных v0: прогноз vs факт, ревизии, трейс | 2 | 2.5 | LOC-17, LOC-23 |
| [LOC-27](https://linear.app/localhosters/issue/LOC-27) | Питч и `docs/value.md`: 5 чисел с источниками и формула ценности в KZT | 3 | 1 | LOC-9 |
| [LOC-7](https://linear.app/localhosters/issue/LOC-7) | Brev-инстанс как общий dev-box + проверка проброса порта | 2 | — | — |

Итого 12.5 ч (P1–P2: 11.5 ч) + LOC-28 0.5 ч. LOC-7 — инфраструктура, без оценки.

### Бюджет часов

| Кто | Воркстрим | из них P1–P2 | Синки (LOC-29 + LOC-30) | Всего |
|---|---|---|---|---|
| Akylbek | 12 | 9.5 | 2.5 | 14.5 |
| Ramazan | 12.5 | 9 | 2.5 | 15 |
| Birzhan | 12.5 | 11.5 | 2.5 + 0.5 (LOC-28) | 15.5 |

Бюджет фазы ~12 ч на человека → P3–P4 задачи (Akylbek 2.5 ч, Ramazan 3.5 ч, Birzhan 1 ч) — тайм-боксы, режутся первыми. LOC-6 и LOC-7 в бюджет не входят.

---

## Общие точки синхронизации

| Linear | Что | Когда | Кто | ч | Зависит от |
|---|---|---|---|---|---|
| [LOC-28](https://linear.app/localhosters/issue/LOC-28) | Вопросы организаторам | 1-й час | Birzhan | 0.5 | — |
| [LOC-29](https://linear.app/localhosters/issue/LOC-29) | Синк 1 | ≈4-й час, 30 мин | все | 0.5 | LOC-8, LOC-16, LOC-14, LOC-21 |
| [LOC-30](https://linear.app/localhosters/issue/LOC-30) | Синк 2 | ≈11-й час, 2 ч | все | 2 | LOC-12, LOC-17, LOC-23, LOC-26 |

**LOC-28 — вопросы организаторам.** Одно сообщение в Q&A-канал: (1) метрика — MAE/RMSE, нормировка, per turbine или сумма; (2) таймзона выходных меток и на каких часах их скрытые актуалы; (3) что значит «прогноз на 31 января» — момент выпуска, границы 48 ч, допустимы ли intraday re-issue; (4) формат CSV; (5) как считаются часы без SCADA-данных; (6) допустим ли Open-Meteo как «открытый источник» или ожидается сырой ECMWF/GFS. Ответа не ждём: дефолты (часы SCADA, MAE → P50, per turbine, issue 18:00 UTC D−1, 48 ч с 00:00 D+1 SCADA) записаны в `docs/research/questions.md` и `docs/assumptions.md`.

**LOC-29 — Синк 1.** После него ни один спайк не меняет схему времени и источников. Решаем: UTC+6 фикс (png от Akylbek); primary Single Runs `ecmwf_ifs` + secondary Previous Runs 5 моделей с маской доступности; Historical Forecast / ERA5 — только train; `best_match` запрещён; issue 18:00 UTC D−1 → 06Z primary + re-issue на 12Z, `ISSUE_HOUR_UTC`; 29 issue-дней и колонки submission CSV; holdout Feb 2025 + Jan 2026; point = P50 по дефолту; rubric-map — кто что доказывает; 2–3 фичи оригинальности. Выход: `docs/research/decisions.md` (≥8 строк «решение / кто / почему»), константы `SCADA_TZ_OFFSET_HOURS`, `ISSUE_HOUR_UTC`, `AVAIL_LAG` в одном `config.py`; Ramazan и Akylbek подтверждают, что parquet-схемы совпадают.

**LOC-30 — Синк 2.** Конец фазы = зелёный прогон 29 issue-дней на реальных данных с моделью v1 в scripted-режиме — это и есть MVP. Делаем: `predict()` из контракта модели → `predict_power`, кеш Single Runs → `fetch_nwp_forecast`, `Clock` → `get_clock`, `metrics.py` → `evaluate_forecast`; `python -m windagent backtest --window test --llm scripted` и `--window dev`; `make verify` на чужой машине; смотрим дашборд; проходим rubric-map по статусам; составляем бэклог сборки в Linear (milestone «Build») с порядком «что режем при нехватке времени»: GRIB → cost-aware → стекинг → фичи дашборда. Выход: `submission/forecast_feb2026_v1.csv` (2 784 строки), MAE dev-окна ≤0.25 (цель ≤0.22) в README «Результаты», `tests/test_clock_no_leakage.py` и `tests/test_feature_schema.py` зелёные, у каждой build-задачи владелец, оценка и ссылка на артефакт ресёрча. Hard stop.

---

## Риски и меры

| Риск | Мера |
|---|---|
| Archive-эндпоинты Open-Meteo (Single Runs, Previous Runs, Historical Forecast) помечены Professional; могут перестать отвечать без ключа или упереться в лимит (10 000/день, weighted-вызовы) | Кешировать и коммитить все raw JSON + `manifest.json` в первые 2 часа; `OPEN_METEO_CACHE_ONLY=1` как режим для жюри; офлайн-прогон как тест; резать запросы по 2 недели; GRIB-адаптер ECMWF AWS как независимый fallback (тайм-бокс) |
| Жюри оспорит «архивность»: `previous_dayN` смешивает 4 рана дня D−N, часть публикуется после полуночи; 12Z ран недоступен в 18:00 UTC под правилом +7h | Primary — Single Runs с явным `run_init_utc` и `lead_h`; правило `init + 7h ≤ issue_time` в `Clock` → 06Z primary, re-issue на 12Z; unit-тест на весь submission с assert против Historical / Archive / ERA5 в test-окне; абзац в README; `previous_dayN` только через маску доступности |
| Актуалы Feb 2026 скрыты — «анализ результата → пересчёт» нельзя показать на тестовом окне; README заявит логику, которую код не подтверждает (−25 баллов) | Dev-окно Jan 2026 с фактами (evaluate / drift / residual alert) + test-окно Feb 2026 с `NWP_RUN` / `DIVERGENCE`; оба в одной команде `make backtest`; таблица ≥5 LLM-решений с полем в trace; трейсы закоммичены |
| LightGBM v1 не побьёт 0.22 MAE (мало lead-aligned данных: aifs с 2025-03, `ecmwf_ifs` с 2025-10; Feb 2025 вне train) | Порог приемлемости ≤0.25; v0 = MOS + логистическая кривая в скелете бэктеста (страховочный submission к ~8-му часу); NaN-признаки для моделей с коротким архивом; go/no-go по HF pre-train (LOC-31) и дампу Single Runs (LOC-18) как резерв данных |
| Ошибка таймзоны / единиц: Open-Meteo по умолчанию km/h, `timezone=auto` сдвигает окно дня; Jan 2026 кросс-корреляция по ветру давала −5…−5.5 ч | Всегда `timezone=UTC&wind_speed_unit=ms`; фиксированный сдвиг −6 ч в одном `scada.py` и `SCADA_TZ_OFFSET_HOURS`; `tz_check.py` → png как sanity и артефакт README; цена ошибки на 1 ч ≈0.005 MAE |
| У экспертов нет `ANTHROPIC_API_KEY` или сети — LLM-путь не воспроизводится | `LLM_MODE=scripted` — основной путь в «Проверке основного сценария»; `make verify` <2 мин офлайн, проверен на чужой машине и в Docker ещё в ресёрче; LLM-трейсы закоммичены; `TestModel` в pytest |
| Три параллельных спайка сделают три схемы признаков / времени и не соберутся в E2E | Синк 1 фиксирует время / источники / формат; контракт модели (`FEATURES`, `build_features`) с тестом train == inference и схемы tools — до Синка 2; один parquet SCADA и один parquet NWP как единственные входы; общий `metrics.py` |
| Организаторы скорят иначе (RMSE, сумма турбин, UTC, другой момент выпуска); обе турбины в одной NWP-ячейке — per-turbine прогноз «размазывается» | Вопросы отправлены в первый час; `docs/assumptions.md` с «если иначе → что меняем» и параметром конфига; выход содержит UTC и SCADA-время, P50 и mean; `turbine_id` + SCADA-лаги как различающие признаки, `|bias|` по турбине <0.02 |
| Ресёрч расползается (GRIB, cost-aware, аблации) и съедает время сборки; Синк 2 занимает больше 2 ч | P3–P4 задачи с тайм-боксами, при провале → «Развитие»; deep-модели и платные провайдеры исключены; Синк 2 — hard stop с порядком «что режем» |

---

## Что дальше

После Синка 2 начинается фаза сборки (milestone «Build» в Linear). Вход в неё: `submission/forecast_feb2026_v1.csv`, зелёные leak- и schema-тесты, `make verify` на чужой машине, бэклог с владельцами и оценками, каждая задача ссылается на артефакт ресёрча.

Порядок сборки: LLM-планировщик поверх scripted (те же ≥5 решений, `LLM_MODE=anthropic`) → дашборд по `docs/demo-storyboard.md` → README по чек-листу организаторов → раздел «Развитие» из тайм-боксов, которые не закрылись. Что режем при нехватке времени: GRIB → cost-aware → стекинг → фичи дашборда.

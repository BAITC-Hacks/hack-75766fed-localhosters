# Результаты ресёрча — верифицированные факты

Единый источник фактов команды по итогам фазы ресёрча (5 агентов: site-domain, eda, weather-archives, ml-approaches, agentic-architecture; live-проверки 2026-09-23). Всё ниже — из `research.json`; пункты без подтверждения помечены «(не подтверждено)». Числа в нормированных единицах мощности (0..1), если не сказано иное.

---

## 1. Площадка

**ВЭС «Нурлы» 5 МВт**, Масакский сельский округ, Енбекшиказахский район, Алматинская область. Оператор — Samruk-Green Energy (Samruk-Energo). Источники: [samruk-green.kz](https://samruk-green.kz/index.php/ru/projects/1047-20210219-133650), [thewindpower.net](https://www.thewindpower.net/windfarm_en_30769_nurly.php), OSM relation 14072944.

| Параметр | Значение | Источник |
|---|---|---|
| Турбины | 2 × Goldwind GW109/2500, 2.5 МВт, ротор 109 м, PMDD, 690 В | [wind-turbine-models](https://en.wind-turbine-models.com/turbines/1193-goldwind-gw-109-2500), [windfair](https://w3.windfair.net/turbine/693-goldwind-gw-109-2500) |
| Ступица | **80 м** (страница оператора) vs **90 м** (spec sheet) — конфликт, см. §7 | те же |
| Cut-in / rated / cut-out (spec) | 3 / 10.3 / 25 м/с | spec sheet |
| Cut-in / 50% / rated (эмпирика SCADA) | ≈3.0 / ≈7.9 (site-domain по 1-м/с бинам: ~8.5) / ≈11.0 м/с; ≥0.95 стабильно от ~12 м/с; cut-out не наблюдался (max ws 22.97 T1 / 21.43 T2; 14 строк ≥20 м/с за 3 года) | CSV |
| Координаты (задание) | T1 43.64515, 78.535604; T2 43.643198, 78.538828 | task context |
| OSM-узлы | 9690012914 (43.64521, 78.53554), 9690012913 (43.64328, 78.53877); расхождение с заданием ≈10 м; расстояние T1–T2 338 м | Overpass |
| Строительство / ввод | март–ноябрь 2018, PowerChina Zhongnan Engineering, грант КНР→РК по соглашению 26.09.2011; ввод 20.07.2020 | samruk-green.kz |
| Плановая выработка | ~16 ГВт·ч/год | samruk-green.kz |
| Нормализация мощности | «активная мощность на стороне линии» = 网侧有功功率 (grid-side converter) ÷ 2.5 МВт, округление до 0.01 (не подтверждено) | [zhihu](https://zhuanlan.zhihu.com/p/676811757), [sciencedirect](https://www.sciencedirect.com/topics/engineering/grid-side-converter) |

**Соседи (Шелекский коридор):**

| Объект | Мощность | Где | Примечание |
|---|---|---|---|
| Energia Semirechya | 60 МВт, 24 × GW130-2.5, 226 ГВт·ч/год, ввод июль–сентябрь 2022 | ~18 км ВСВ, 43.7117/78.7440 | Samruk-Energo 25% / Hydrochina 50% / PowerChina 25%; [gem.wiki](https://www.gem.wiki/Shelek_(Energia_Semirechya)_wind_farm) |
| Zheruyik Energo | 48.5–50 МВт, 25 × Vestas, 2022 | тот же коридор | [ebrdgeff](https://ebrdgeff.com/kazakhstan/projects/large-scale-wind-farm-in-the-shelek-corridor-of-the-enbekshikazakh-district-of-the-almaty-region/) |
| ~13 нетегированных турбин в OSM | ? | 0.3–1.1 км W/NW от T1/T2, нанесены 2022 и 2025 | вероятно ТОО «Нурлы ВЭС» 4.5 + 5 МВт → риск wake при западном ветре в 2024–2026 (не подтверждено) |

**Грид-пойнты Open-Meteo для координат T1** (высота площадки ~600 м):

| Модель | Грид | Высота грида |
|---|---|---|
| ecmwf_ifs (9 км) | 43.620384 / 78.47891 | 555 м |
| ecmwf_ifs025, ERA5 | 43.75 / 78.5 | — |
| icon_global | 43.625 / 78.5 | — |
| gfs_global | 43.638 / 78.516 | — |

**Ближайшие метеостанции** (NOAA ISD): Malibay 36894 (43.483N 78.400E, 870 м, 21 км ЮЮЗ, SYNOP 3-часовой 00/03/…/21 UTC, [ISD 2025](https://www.ncei.noaa.gov/pub/data/noaa/2025/368940-99999-2025.gz), [meteostat bulk](https://bulk.meteostat.net/v2/hourly/36894.csv.gz)); Chilik/Shelek 36891 (28 км W, meteostat 404); Assy 36897 (закрыта 2022). Ogimet отдаёт 403 скриптам. [Kazhydromet DB](https://meteo.kazhydromet.kz/database_meteo) — по регистрации, обновление раз в месяц, не операционно. Не замена NWP.

**Климат площадки** (SCADA + ERA5 2023-03-11..2026-01-31):

| Показатель | Значение |
|---|---|
| Средний ветер (гондола) | 6.45 м/с; Weibull k≈1.80, c≈7.25 м/с |
| Доля времени ≥3 / ≥12 / ≥20 м/с | 77% / 8.6% / 0.01% |
| CF по годам | 2023 0.363, 2024 0.403, 2025 0.355, янв 2026 0.316 |
| Месячный ветер, м/с | Dec 7.67, Nov 7.09, Mar 7.05, Feb 6.87, Apr 6.87 … Jul 5.39, Aug 5.21 |
| Месячная мощность | Dec 0.483, Nov 0.434, Mar 0.433, Apr 0.416, Feb 0.404, Jan 0.368 … Jul 0.259, Aug 0.260 |
| Февраль по годам | 2024: p 0.454, ws 7.39, T −1.3 °C; 2025: p 0.352, ws 6.33, T +1.2 °C (p<0.05 в 33% строк, p>0.9 в 17%) |
| Направления (ERA5 100 м) | W 25%, NE 24.5%, E 21%, SW 16% — бимодально вдоль коридора; при ≥8 м/с: W 41%, E+NE 45% |
| Суточный ход ветра (часы UTC+6) | max 18–20 ч, min 05 ч |
| Температура | −19…+44 °C; средние Jan −0.82, Feb −0.07, Dec 0.71 °C |
| ERA5 100 м vs гондола | r≈0.75–0.80 почасово, занижает ~1 м/с (5.3 vs 5.9–6.5); ws_site ≈ 1.078·ERA5 + 1.40, отношение средних 1.39, corr 0.67–0.83 (mean 0.74) |

Пресс-релизы (7.8 м/с на 50 м, [samruk-energy.kz](https://www.samruk-energy.kz/ru/press-center/company-news/11-novosti/1017-v-shelekskom-koridore-v-2022-godu-zarabotaet-novaya-vetroelektrostantsiya)) завышены относительно наблюдений.

---

## 2. Данные SCADA

Файлы: 10-мин шаг, 2023-03-11 → 2026-01-31 23:50. T1 142,360 строк, T2 149,499. Дубликатов 0, минуты ровно :00..:50. Всего 25,392 часов в диапазоне. Колонки: `ID`, `Статистическое время`, `Средняя скорость ветра(m/s)`, `Нормализованная активная мощность`, `Средняя температура окружающей среды(°C)`.

### 2.1 Таймзона — фиксированный UTC+6 (verified: site-domain, weather-archives; eda — likely из-за января 2026)

`t_utc = t_scada − 6 h` для ВСЕХ строк. Часы SCADA **не** переключились 2024-03-01, когда Казахстан перешёл на UTC+5 ([timeanddate](https://www.timeanddate.com/news/time/kazakhstan-single-time-zone.html), [gov.kz](https://www.gov.kz/memleket/entities/mti/press/news/details/688998?lang=ru)). Localize как `Etc/GMT-6`, никогда как `Asia/Almaty`.

Доказательства:

| Тест | Результат |
|---|---|
| Непрерывность вокруг 2024-03-01 00:00 | 25 строк 22:00–02:00 (ожидалось 25), 0 дублей, нет пропущенного часа в обоих файлах |
| Суточный ход температуры | argmax = 15 ч, argmin = 6–7 ч до и после 2024-03-01, во все сезоны. Солнечный полдень на 78.5°E = 06:46 UTC → Tmax ~09:30 UTC = 15:30 при UTC+6 |
| Кросс-корреляция ветра с ERA5/IFS (UTC), 10-мин | site-domain: best lag 6.00 ч до (r=0.759), 5.83 ч после (r=0.788), плато 5.67–6.33; weather-archives: +5.83 ч во всех 6 периодах × 2 турбины (r≈0.76–0.82); eda: помесячно −5.67…−6.50, mean −6.09 ч (до 2024-03: −6.33, после: −5.97) |
| Температура | best lag 6.67–7.0 ч (гондольный датчик отстаёт от 2 м на ~0.8 ч), r=0.949–0.986 |
| Цена ошибки в 1 ч | ERA5-кривая MAE 0.177 при +6 vs 0.182 при +5 (autocorr 0.90 на лаге 1 ч) |

Единственная неоднозначность: январь 2026 по ветру даёт −5.0…−5.5 ч, но температура и суточный пик по-прежнему +6. Начало или конец 10-мин окна метит `Статистическое время` — не установлено (±5–10 мин, топ корреляции плоский) (не подтверждено). Рекомендация: `resample('h', label='left', closed='left')`, зафиксировать допущение в README.

Deadline рынка 08:00 Астаны (UTC+5) = **03:00 UTC**.

```python
df = df.rename(columns={'Статистическое время':'t','Средняя скорость ветра(m/s)':'ws','Нормализованная активная мощность':'p','Средняя температура окружающей среды(°C)':'temp'})
df['t_utc'] = pd.to_datetime(df['t']) - pd.Timedelta(hours=6)   # fixed UTC+6, все строки
hourly = df.set_index('t_utc')[['ws','p','temp']].resample('h', label='left', closed='left').mean()
```

### 2.2 Качество, пропуски, флаги

| Факт | T1 | T2 |
|---|---|---|
| Квантование мощности | шаг 0.01, 101 уникальное значение; floor 0.01 в 23.3% строк; p==0 ровно — 534 строки | floor 0.01 в 22.3%; p==0 — 2,680 |
| Cap (медиана p при ws>12.5) | 0.99 всегда | **0.97** до 2025Q4, **0.99** с 2026Q1 (q90 0.99 уже в 2024Q4–2025Q1) |
| Пропуски | 6.56% (9,992 из 152,352 строк, 67 разрывов, 1,665 ч) | 1.87% (2,853 строк, 178 разрывов, 475 ч) |
| Разрывы >24 ч | 2024-05-18 03:40→06-28 18:40 (999 ч); 2024-06-28 23:00→07-17 17:20 (450 ч); 2025-10-03 10:40→10-05 14:00 (51.3 ч); 2025-05-23 18:50→05-24 23:00 (28.2 ч) | 2024-05-18 04:00→05-20 13:30 (57.5 ч); 2025-10-03→05 (51.3 ч); 2024-02-16 12:20→02-17 18:40 (30.3 ч); 2025-05-23→24 (28.2 ч); 2023-04-14 15:40→04-15 18:00 (26.3 ч) |
| Часы с <6 сэмплов | 1,725 (6.8%: 1,629 пустых, 96 частичных) | 607 (2.4%: 388 пустых, 219 частичных) |
| Простои: p≤0.01 & ws>5 | 1,640 строк (1.15%) | 1,289 (0.86%) |
| Остаток < −0.3 от кривой | 1,261 (0.89%); топ-месяцы 2023-11 (242), 2025-05 (226), 2023-07 (212) | 845 (0.57%); 2025-02 (167), 2024-11 (115) |
| Самый долгий ноль при ветре | 39.3 ч с 2023-11-15 18:00 (ws 8.1) | 21.2 ч с 2025-02-23 17:40 (ws 8.7) — внутри февраля |
| Залипание датчика | 2025-05-14 12:10–15:30 (20 строк ws=0.0, temp 34.09) — единственный freeze | нет |
| Скачки \|Δp\|>0.5 за 10 мин | 346 | 290 |

- 28 из 31 разрывов T1 >1 ч перекрываются с T2; типичные общие дырки — дневные окна 10:00–12:00 → 16:00–18:00 (обслуживание). Пустые часы: только T1 1,371, только T2 130, оба 258.
- Curtailment-плато нет: при 13–20 м/с 5–99-й перцентили 0.98–0.99, ~36 строк в 0.6–0.9.
- Простои по годам (T1): 2023 1.3%, 2024 0.4%, 2025 0.9%, 2026 0.4%.
- Холод/обледенение: при T<−5 °C & ws>5 доля p≤0.01 = 3.23% vs 2.15% при T≥5 (T1), 4.41% vs 1.23% (T2); при T<−2 vs T>5 недовыработка 3.7% vs 2.5%. Плотность воздуха: при 8–9 м/с средняя p 0.609 (T<−10) → 0.601 (−10..0) → 0.618 (0..10) → 0.583 (20..30) → 0.565 (>30).
- Скачки температуры >5 °C — только на краях разрывов; >10 °C нет. Диапазон Jan −16.4..11.1, Jul 19.4..43.5.

Полные списки разрывов: scratchpad `eda/gaps_T1.csv`, `gaps_T2.csv`; загрузчик — scratchpad `eda/load.py`.

### 2.3 Распределение почасовой мощности (T1, n≥4)

mean 0.371, std 0.359, q05 0.010, q25 0.033, q50 0.237, q75 0.698, q90 0.975. Бимодально: [0,0.1) 36.1%, [0.9,1] 16.0%; p<0.05 28.6%, p>0.95 12.6%. T2 mean 0.366, median 0.228. Следствие: MAE минимизируется медианным прогнозом, RMSE — средним; выбор точечного прогноза зависит от метрики организаторов.

Суточный ход слабый: min 0.333 @07, max 0.409 @19 (зима ±0.04). Автокорреляция почасовой p: lag1 0.901, lag2 0.778, lag3 0.673, lag6 0.418, lag12 0.146, lag24 0.098, lag48 0.071, lag168 0.067. Лаги SCADA полезны только на h≤6.

### 2.4 Кривая мощности

Бины 0.5 м/с, медиана p (T1): 0.03 @3.0, 0.15 @5.0, 0.40 @7.0, 0.71 @9.0, 0.93 @10.5, 0.98 @11.0, 0.99 с 11.5 до 21 м/с. IQR в крутой зоне 0.03–0.06. Макс. наклон 0.176/м/с при 7.9 м/с (0.11 при 6 и 10) → ошибка ветра 1 м/с ≈ 0.11–0.18 мощности. 47% часов (49–52% в Feb 2025 / Jan 2026) — в крутой зоне 5–11 м/с.

Логистическая аппроксимация:

| | Формула | R² / MAE (10-мин) | R² / MAE / RMSE (час) |
|---|---|---|---|
| T1 | p = 1/(1+exp(−0.705·(ws−7.89))) | 0.957 / 0.034 | 0.962 / 0.031 / 0.070 |
| T2 | a=0.700, b=7.98 | 0.970 / 0.030 | 0.973 / 0.029 / 0.058 |

Эмпирическая binned-median кривая: MAE 0.030 / 0.028. **Потолок при идеальном ветре — MAE ≈0.03**; вся ошибка прогноза придёт из NWP-ветра. Гондольный анемометр стоит за ротором и занижает свободный поток ([WES 2017](https://wes.copernicus.org/articles/2/295/2017/wes-2-295-2017.pdf)) — spec-кривую не использовать, NWP-ветер напрямую в SCADA-кривую не подставлять без калибровки.

```python
def power_curve(ws, a=0.705, b=7.89, cap=0.99, floor=0.01):
    return np.clip(1/(1+np.exp(-a*(np.asarray(ws,float)-b))), floor, cap)
```

### 2.5 Бейзлайны (MAE, T1)

| Бейзлайн | Feb 2025 (n=1,334 ч) | Jan 2026 (n=1,440 ч) |
|---|---|---|
| same-hour-yesterday | 0.400 (RMSE 0.515) | 0.370 |
| last-value (persistence) | 0.408 (h1–24 0.372, h25–48 0.445) | 0.335 (h1–24 0.309) |
| mean последних 7 дней | 0.326 | 0.295 |
| hour-of-day mean последних 7 дней | 0.327 | 0.299 |
| климатология month×hour | 0.344 | 0.306 |
| константа = среднее месяца | 0.346 | 0.309 |
| **константа = медиана (0.237)** | **0.305** | **0.273** |
| ноль | 0.352 | 0.316 |
| ERA5-ветер → кривая (LOMO) | 0.200 | 0.173 |
| идеальный ветер → кривая | 0.03 | 0.03 |

Jan 2025: last-value 0.277 (h1–24 0.238), same-hour 0.338, mean-7d 0.352. T2 в пределах ±0.03 от T1. По всему датасету (site-domain): 24h-persistence 0.368, климатология month×hour 0.307. ERA5-кривая leave-one-month-out по 9 месяцам: 0.194 (2023-07), 0.184 (2023-12), 0.209 (2024-02), 0.153 (2024-04), 0.173 (2025-01), 0.200 (2025-02), 0.165 (2025-07), 0.146 (2025-10), 0.173 (2026-01); mean 0.177, RMSE 0.20–0.27.

Число, которое надо побить: **0.27–0.30** (медианная константа). Всё выше 0.30 — не лучше отсутствия модели. Реалистичная цель с архивным NWP: **0.18–0.25**.

### 2.6 Корреляция T1/T2

141,357 общих 10-мин меток. Мощность corr 0.9641 (10-мин) / 0.9703 (час), mean |Δp| 0.0345 / 0.0267, bias −0.001. Ветер corr 0.9896, mean |Δws| 0.372 м/с, T1−T2 = −0.083 м/с. Температура corr 0.9998. |p1−p2|>0.5 в 0.99% строк; никогда одна на 0 при другой >0.5. Средняя p 2025: 0.3545 vs 0.3546. Вывод: одна модель на обе турбины с признаком turbine_id; T2 — прокси для дыры T1 май–июль 2024.

---

## 3. Источники прогнозов погоды

Live-проверки 2026-09-23 для координат T1, без ключа. Единственные бесплатные источники **as-issued** прогнозов за 31.01–28.02.2026 с часовым шагом: Open-Meteo Previous Runs + Single Runs, плюс сырые GRIB ECMWF/NOAA на AWS.

### 3.1 Таблица API

| API / endpoint | Что возвращает | Lead-семантика | Модели, старт архива | Полнота Feb 2026 | Лимиты / лицензия |
|---|---|---|---|---|---|
| **Previous Runs** `previous-runs-api.open-meteo.com/v1/forecast`, `hourly=<var>_previous_dayN` ([docs](https://open-meteo.com/en/docs/previous-runs-api), [blog](https://openmeteo.substack.com/p/weather-forecasts-from-previous-model-runs)) | для валидного часа h дня D — значение из прогона дня D−N того же 6-ч блока; N=1..7; только целые сутки (нет 6/12/36 ч) | **N=1: lead 24–29 ч, N=2: 48–53 ч** — верифицировано против Single Runs (prev_day1 Feb-1 00–05 = run 01-31T00 часы 24–29; 06–11 = run 01-31T06 и т.д.); previous_day0 == live | ecmwf_ifs025 / icon_global / gfs_global / best_match с **2024-03** (2024-02-15 null); ecmwf_aifs025_single с 2025-03; ecmwf_ifs 9 км с 2025-10 (2025-09-15 null); GFS temperature_2m с 2021-04 (ветер — нет). Null здесь: gem, jma, ukmo, gfs_graphcast025, bom; meteofrance/cma — только day0 | **696 ч, 0 null** (ws100 day1/day2, ws10, t2m, wdir100, sp) для ecmwf_ifs, ecmwf_ifs025, ecmwf_aifs025_single, icon_global, gfs_global; также gfs_seamless, icon_seamless, best_match (24/24). wind_gusts_10m null для всех ECMWF (есть у icon/gfs); icon day7 null | free tier |
| **Single Runs** `single-runs-api.open-meteo.com/v1/forecast?run=YYYY-MM-DDTHH:00&models=ecmwf_ifs` ([docs](https://open-meteo.com/en/docs/single-runs-api), [blog](https://openmeteo.substack.com/p/single-runs-api)) | полный часовой горизонт одного прогона; t0 = run | явный init + lead_h на каждое значение — самое сильное доказательство «прогноз, доступный на момент» | **ecmwf_ifs (IFS HRES 9 км)** прогоны 00/06/12/18 UTC с **2024-03-14** (2024-03-13 → 400); 00Z/12Z почасово до 240 ч (данные до 360 при forecast_days=16, грубее после 144 ч), 06Z/18Z до 144 ч. Другие модели (ifs025, icon_global, gfs_global, aifs) — только с 2026-04-02 → 400 для Feb 2026 | **все 116 прогонов** 31.01–28.02.2026 по 72 ч, 0 null (сохранено: scratchpad `single_runs_ecmwf_ifs_feb2026.csv`) | free tier |
| **Historical Forecast** `historical-forecast-api.open-meteo.com/v1/forecast` ([docs](https://open-meteo.com/en/docs/historical-forecast-api)) | сшивка первых часов каждого прогона | **lead 0–5 ч** (near-analysis): часы 00–05 из 00Z, 06–11 из 06Z… — верифицировано (Feb-1 06–11 = run 02-01T06 часы 0–5). **НЕ для Feb 2026** — только train | IFS HRES 9 км с 2017-01-01, IFS 0.25 с 2024-02-03, ICON 2022-11-24, GFS 2021-03-23, GEM 2022-11-23, ARPEGE 2022-11-13, UKMO 2022-03-01, JMA 2016. Здесь best_match = ecmwf_ifs (идентичные значения; knmi/dmi тоже на него падают) | 0 null: ws10/80/100/120, wdir10/100, gusts10, t2m, sp, msl, rh2m; t80/t120 null у ecmwf_ifs (есть у gfs/icon). 3 года × 14 переменных одним вызовом: ecmwf_ifs 2.1 с, gfs_global 16 с, icon_global 37 с | free tier |
| **Archive (ERA5)** `archive-api.open-meteo.com/v1/archive?models=era5` ([docs](https://open-meteo.com/en/docs/historical-weather-api)) | реанализ ERA5 0.25° (грид 43.75/78.5), задержка 5 дней | факт, не прогноз — только train/eval | без `models` best_match = **IFS 9 км analysis**, побайтно = Historical Forecast ecmwf_ifs (max abs diff 0.0 за Feb 2026) — **не ERA5**. era5_land — нет 100 м ветра; era5_ensemble 0.5° работает; ecmwf_ifs_analysis_long_window (2024+) работает; cerra → 400 | ERA5 0 null 2023-03-11..2026-01-31: ws10/100, wdir10/100, gusts10, t2m, sp, msl, rh2m; ws80/120, t80/120 null. 3 года — 2.6 с | free tier |
| **Live Forecast** `api.open-meteo.com/v1/forecast` | текущий прогноз (live-режим агента) | past_days ≤92, forecast_days ≤16 (17 → 400) | 80/100/120/180 м + gusts: ecmwf_ifs, icon_global, meteofrance_seamless, cma_grapes_global; ecmwf_ifs025 и aifs — только 100 м (aifs без gusts); gfs_global 80/100/120; gfs_graphcast025, kma_seamless — null | — | free tier |
| **ECMWF Open Data на AWS** `s3://ecmwf-forecasts` (eu-central-1, [registry](https://registry.opendata.aws/ecmwf-forecasts/)) | сырые GRIB2 каждого прогона с 2023-01-18 | явный init + step; 3-часовые шаги → нужна интерполяция до часа | IFS 0.25 (oper/scda/enfo), AIFS `aifs-single/0p25/oper` (есть 100u/100v) | все прогоны 2026 | CC-BY 4.0; S3 `SlowDown` при burst — backoff |
| **NOAA GFS/GEFS на AWS** `s3://noaa-gfs-bdp-pds`, `s3://noaa-gefs-pds` ([registry](https://registry.opendata.aws/noaa-gfs-bdp-pds/)) | GRIB2 0.25°, часовые шаги до 120 ч; `.idx` для byte-range | явный init + step | GFS с 2021-02; UGRD/VGRD на 10/20/30/40/50/80/100 м, TMP 2/80/100 м, GUST, PRMSL; GEFS 31 членов (80/100 м только в `pgrb2bp5` 0.5°) | f024 файл 538 МБ (`gfs.20260201/00/atmos/gfs.t00z.pgrb2.0p25.f024`) | NOAA open data; NOMADS → 403 (~10 дней retention) |
| **Open-Meteo raw DB на AWS** `s3://openmeteo` (us-west-2, [registry](https://registry.opendata.aws/open-meteo/)) | OM-файлы всех моделей (`data/ecmwf_ifs/`, `data/dwd_icon/`, `data/copernicus_era5/` …), обновление ежечасно | self-hosting API через Docker — снимает rate-limit и коммерческие ограничения | | | CC-BY 4.0 |

**Лимиты Open-Meteo** ([pricing](https://open-meteo.com/en/pricing), [terms](https://open-meteo.com/en/terms)): без ключа, только non-commercial; 600 вызовов/мин, 5,000/ч, 10,000/день, 300,000/мес; запрос >10 переменных или >2 недель на локацию считается за несколько вызовов (2 недели × 15 переменных = 1.5, 4 недели = 3.0). Данные CC-BY 4.0. IFS HRES 9 км нативно (O1280) под CC-BY 4.0 с 2025-10-01. За ~350 тестовых вызовов ни одного 429. **Риск:** pricing-страница помечает Historical Weather / Historical Forecast / Previous Runs / Single Runs как Professional-only, но публичные endpoint'ы отвечают без ключа → кэшировать каждый сырой ответ в репо (`data/nwp_cache/`). Объём: Feb-replay ≈ 29 single-run + 5 previous-runs вызовов.

### 3.2 Ловушки

1. **Historical Forecast и Archive best_match = lead 0–5 ч.** Это near-analysis; использовать для Feb 2026 = нарушить правило «архивный прогноз, а не поздний факт». Только для train.
2. **`models=best_match` в Archive возвращает IFS 9 км, не ERA5.** Реанализ — только явно `models=era5`. Иначе README опишет источник неверно.
3. **Ветер по умолчанию в km/h.** Всегда `wind_speed_unit=ms` (5.6 km/h → 1.55 m/s). Без параметра Single Runs даёт ws100 30.9 km/h вместо 8.57 m/s.
4. **`timezone=auto` / `Asia/Almaty` сдвигает окно.** Даёт GMT+5 (utc_offset 18000), времена локальные, значение Feb-1 00:00 меняется (7.6 vs 5.6); Single Runs также сдвигает метку прогона (t0 2026-01-31T05:00). Всегда `timezone=UTC`, а SCADA — фиксированный −6 ч.
5. **`best_match` в Previous Runs здесь сейчас резолвится в ecmwf_ifs 9 км** (архив 9 км в этом API — с 2025-10), при этом сам `best_match` отдаёт данные с 2024-03 → ряд неоднороден по подлежащей модели; для train-окна 2024–2026 брать явные модели.
6. Previous Runs: только целосуточные смещения (нет 6/12/36 ч) — точный прогноз «на момент выпуска» не восстановить; для этого Single Runs.
7. `timeformat=unixtime` даёт epoch (1769904000 = 2026-02-01T00:00Z) — удобно для join.
8. Модели сильно расходятся: 2026-02-01T00:00Z ws100 best_match 1.55, ECMWF 4.30, ICON 1.46, GFS 8.00 м/с; previous_day1: 1.49 / 0.63 / 1.77 / 10.78 → мультимодельный ансамбль обязателен.

### 3.3 Skill моделей vs SCADA (T1, Nov 2025–Jan 2026, ws100 почасово, м/с)

| Модель | day1 (24–29 ч) r / RMSE / bias | r с мощностью | day2 (48–53 ч) r | day0 r |
|---|---|---|---|---|
| ecmwf_aifs025_single | 0.795 / 2.65 / −1.40 | 0.767 | 0.784 (RMSE 2.83, bias −1.65) | 0.795 |
| icon_global | 0.789 / 2.67 / +0.23 | 0.758 | 0.736 (RMSE 2.97, bias +0.23) | 0.843 |
| ecmwf_ifs (9 км) | 0.756 / 2.72 / −1.22 | 0.741 | 0.733 | 0.813 |
| ecmwf_ifs025 | 0.747 / 2.91 / +1.07 | 0.726 | 0.716 | — |
| gfs_global | 0.699 / 3.50 / +1.70 | 0.681 | 0.636 | — |

icon_global `wind_speed_80m` day1 r 0.805 — лучше своих 100 м. SCADA ветер → мощность r = 0.949 (n=23,763) — практический потолок. Систематические смещения (ECMWF −1.2..−1.4, GFS +1.7 м/с) велики относительно наклона кривой → per-model bias correction обязательна.

### 3.4 ECMWF AWS GRIB — путь

Layout: `{YYYYMMDD}/{HH}z/ifs/0p25/{stream}/{YYYYMMDD}{HH}0000-{step}h-{stream}-fc.grib2` + `.index`. 00Z/12Z → stream `oper` (0–144 ч каждые 3 ч, далее 6-часово до 360), 06Z/18Z → `scda` (0–144 ч, 3-часово); `enfo` — ансамбль. Surface-параметры в 24-ч файле: 100u, 100v, 10u, 10v, 10fg, 2t, 2d, sp, msl, skt. Файл шага ~128 МБ, но `.index` (JSON-строки с `_offset`/`_length`) даёт byte-range: 100u на 24 ч = 1,405,605 байт; cfgrib → u100 в ближайшем гриде (43.75, 78.5) = −10.52 м/с, valid 2026-02-02T00:00. Клиенты: [ecmwf-opendata](https://github.com/ecmwf/ecmwf-opendata) (`Client(source='aws')`), [Herbie](https://herbie.readthedocs.io/en/latest/gallery/ecmwf_models/ecmwf.html) (`Herbie('2026-02-01', model='ifs', product='oper', fxx=24)`; aws с 2023-01-18, azure с 2022-01-21, ecmwf.int только 4 дня). Выполнено end-to-end (scratchpad `archived_wx.py`, `ecmwf_aws_field`).

Тайминг публикации HRES ([dissemination](https://confluence.ecmwf.int/display/DAC/Dissemination+schedule)): 00z 05:45→06:12 UTC, 06z 11:45→12:12, 12z 17:45→18:12, 18z 23:45→00:12. Open-data 0.25° — ещё +2 ч, 3-часовые шаги ([ecmwf-api](https://open-meteo.com/en/docs/ecmwf-api)). Безопасное правило: HRES доступен с init+7 ч, open-data с init+9 ч. Прогноз «выпущенный 31 января» на 1–2 февраля легитимно = прогон 31-Jan 12Z (публикация ≈18:30 UTC = 23:30 Алматы; lead 12–59 ч на 48-ч окне) (не подтверждено).

### 3.5 Платные альтернативы — одной строкой

OpenWeatherMap History Forecast Bulk — as-issued с 2017-10-07, 4 прогона/день, 10 м ветер, 35 GBP/локация ([owm](https://openweathermap.org/api/history-forecast-bulk)); Visual Crossing Historical Forecast add-on — с 2020-01-01, `forecastBasisDate`, 10 м, цена не опубликована (не подтверждено); Weatherbit — ручной заказ по city-ID, 30 дней хранения, медленно; Meteomatics — архив с 2017, pin прогона через API не подтверждён (не подтверждено); meteoblue — day-1 сшивка, lead не выбрать (не подтверждено); Tomorrow.io / Windy — архива прогнозов нет (не подтверждено); Kazhydromet — WRF 2/4/13/18 км, 24–168 ч, только картинки/текст, без API (не подтверждено). Copernicus CDS `reanalysis-era5-single-levels` — тот же ERA5 по аккаунту (не выполнялось) (не подтверждено). Вывод: платные не нужны.

### 3.6 Три ключевых вызова (curl, все HTTP 200)

```bash
# (1) Previous Runs: lead 24–29 ч / 48–53 ч
curl -s "https://previous-runs-api.open-meteo.com/v1/forecast?latitude=43.64515&longitude=78.535604&hourly=wind_speed_100m_previous_day1,wind_speed_100m_previous_day2&start_date=2026-02-01&end_date=2026-02-03&timezone=UTC&wind_speed_unit=ms&models=icon_global"

# (2) Single Runs: полный горизонт прогона ECMWF IFS 9 км от 2026-01-31 12:00 UTC
curl -s "https://single-runs-api.open-meteo.com/v1/forecast?latitude=43.64515&longitude=78.535604&run=2026-01-31T12:00&models=ecmwf_ifs&hourly=wind_speed_100m,wind_direction_100m,temperature_2m,surface_pressure&forecast_days=3&timezone=UTC&wind_speed_unit=ms"

# (3) Archive ERA5 (явный models=era5!)
curl -s "https://archive-api.open-meteo.com/v1/archive?latitude=43.64515&longitude=78.535604&hourly=wind_speed_100m,wind_speed_10m,temperature_2m,surface_pressure&start_date=2026-02-01&end_date=2026-02-03&timezone=UTC&wind_speed_unit=ms&models=era5"
```

```python
import requests, pandas as pd
P = dict(latitude=43.64515, longitude=78.535604, timezone="UTC", wind_speed_unit="ms")
prev = pd.DataFrame(requests.get("https://previous-runs-api.open-meteo.com/v1/forecast", params={**P, "start_date":"2026-02-01","end_date":"2026-02-03","hourly":"wind_speed_100m_previous_day1,wind_speed_100m_previous_day2","models":"icon_global"}).json()["hourly"])
run  = pd.DataFrame(requests.get("https://single-runs-api.open-meteo.com/v1/forecast", params={**P, "run":"2026-01-31T12:00","models":"ecmwf_ifs","hourly":"wind_speed_100m,wind_direction_100m,temperature_2m,surface_pressure","forecast_days":3}).json()["hourly"])
era5 = pd.DataFrame(requests.get("https://archive-api.open-meteo.com/v1/archive", params={**P, "start_date":"2026-02-01","end_date":"2026-02-03","hourly":"wind_speed_100m,wind_speed_10m,temperature_2m,surface_pressure","models":"era5"}).json()["hourly"])
```

Официальный клиент с кэшем и retry (выполнено против Previous Runs): `openmeteo_requests.Client(session=retry(requests_cache.CachedSession(".om_cache", expire_after=-1), retries=5, backoff_factor=0.5))`.

---

## 4. ML-подход

### 4.1 Литература и соревнования

| Источник | Вывод |
|---|---|
| [HEFTCom2024](https://arxiv.org/pdf/2507.01579) (Hornsea 1, 1.2 ГВт, day-ahead live) | GBDT «reaffirms competitiveness»; 9 из top-10 — GBT. Победитель SVK: CatBoost MultiQuantile отдельно на каждый NWP-источник (DWD, GFS, MEPS), признаки = сырые грид-точки + лаги + разности + календарь, тюнили только n_iterations, квантили клипнуты в capacity, сверху линейная quantile-regression мета-модель по 27 выходам. Третий NWP дал +8% pinball. [Код](https://github.com/BigdogManLuo/HEFTcom24) |
| [GEFCom2014 wind](https://www.sciencedirect.com/science/article/abs/pii/S0169207016000145) | GBM quantile per quantile/zone; главные признаки — NWP ветер 100 м в кубе с ± лагами; входы только 10 и 100 м, без SCADA-лагов |
| [Single-farm 2026](https://www.researchgate.net/publication/406918557) (Ridge/XGB/LGBM/DLinear/Transformer/PatchTST) | LightGBM лучший на hold-out (NRMSE 10.23%), Transformer чуть лучше на rolling (8.17% vs 8.73%); ранжирование нестабильно; «tree-based remain highly competitive» |
| [Bias-correction study](https://arxiv.org/abs/2402.13916) | «changes to neural network architectures play a minor role»; SCADA-коррекция 48-ч NWP: NRMSE 35% → 22%; continuous retraining помогает больше всего |
| [MOS-исследования](https://link.springer.com/article/10.1186/s41601-021-00214-x), [XGBoost corrector](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2025EA004801) | Kalman-коррекция 72-ч WRF: RMSE −16%, MAE −14%; XGBoost: RMSE ветра −26.1% vs raw, −35.6% vs классический MOS; 1% ошибки ветра ≈ 0.6% точности мощности |
| [Multi-NWP](https://pmc.ncbi.nlm.nih.gov/articles/PMC10637996/), GET.transform | 3 NWP-источника снижают ошибку на 8–30%; агрегация турбинных прогнозов бьёт farm-level на 10–15% |
| [KDD Cup 2022](https://arxiv.org/abs/2307.09248) | НЕ шаблон: без NWP, чистые SCADA-history модели; на 24–48 ч без NWP skill плохой |
| [Madsen et al. 2005](http://pierrepinson.com/docs/madsen05_protocol.pdf) | стандартный протокол оценки (см. 4.5); persistence трудно побить только на 4–6 ч |
| [WPBench](https://arxiv.org/html/2609.24444) | nMAE 0.06–0.23 по 26 датасетам; DLinear конкурентен с foundation-моделями |

### 4.2 Рекомендуемый стек (по трудозатратам)

1. Канонический почасовой датасет (UTC, ≥4 из 6 сэмплов, флаги).
2. Бейзлайны: persistence, климатология, Madsen «new reference» a_k·P(t)+(1−a_k)·mean, NWP → binned SCADA-кривая после линейного MOS ws_NWP → ws_nacelle с плотностной нормировкой.
3. **Основная модель: LightGBM `objective='quantile'`, alpha ∈ {0.1, 0.5, 0.9}** (или CatBoost MultiQuantile), pooled по T1+T2 с `turbine_id`. Train на previous_day1/day2 (2024-03 → 2025-12), validate Feb 2025 + Jan 2026. Clip [0,1], сортировка квантилей (нет crossing).
4. Если успеваем: SVK-стекинг (CatBoost per NWP + линейная QR-мета) или просто среднее квантилей по NWP; MAPIE EnbPI (`TimeSeriesRegressor(method='enbpi', cv=BlockBootstrap)`) при плохой калибровке.
5. Опционально для «оригинальности»: nixtla neuralforecast NHITS с `futr_exog_list` = NWP ([docs](https://nixtlaverse.nixtla.io/neuralforecast/docs/capabilities/exogenous_variables.html)); TFT/N-BEATS/LSTM как primary — нет.

Библиотеки: pandas/numpy, lightgbm, catboost, scikit-learn, shap, mapie (опц.), windpowerlib (density/height, опц.), openoa — скопировать 3–4 фильтра вместо тяжёлой зависимости, openmeteo-requests + requests-cache + retry-requests, matplotlib/plotly.

### 4.3 Признаки

| Группа | Признаки |
|---|---|
| NWP ветер | ws 10/80/100/120 м по каждой модели (ecmwf_ifs, icon_global, aifs, ifs025, gfs_global); ws100³; среднее и spread по моделям; лаги/разности ws100 ±1, ±2 ч |
| Направление | sin/cos wdir100 или u/v (u = −ws·sin(dir), v = −ws·cos(dir)) — сектора W vs E/NE решают wake/speed-up |
| Термодинамика | t2m, surface_pressure, ρ = p/(287.05·T), IEC v_n = v·(ρ/1.225)^(1/3) (~20% размах плотности за −19…+44 °C), флаг T<0 / T<−5, gusts (icon/gfs) |
| Сдвиг | α = ln(ws100/ws10)/ln(10) — прокси стабильности; 1/7 не использовать, измеренный α 0.03–0.31 день/ночь |
| Время | hour sin/cos, doy sin/cos, month, lead offset (24/48), hours-since-issue |
| SCADA | последняя мощность и ws на момент выпуска (только h≤6), turbine_id (categorical) |

```python
R_D = 287.05
rho = (p_hpa*100.0) / (R_D*(t_c+273.15)); v_n = ws*(rho/1.225)**(1/3)
```

### 4.4 Очистка (флаги, не удаление; train на чистых, eval на всех)

| Правило | Порог |
|---|---|
| range | ws ∉ [0,30] или p ∉ [0,1] |
| frozen | Δp==0 & Δp(2)==0 & Δws==0; конкретно — 2025-05-14 12:10–15:30 |
| downtime | ws > cut-in+1 & p≤0.005; в EDA-варианте p≤0.01 & ws>5 |
| curtailment / outage | ws > rated & p < 0.6·bin-median; или остаток < −0.3 от логистической кривой (≈1% строк) |
| icing (IEA Task 19, [t19](https://github.com/IEAWind-Task19/T19IceLossMethod)) | T<2 °C & p < P10 бина ≥3 подряд 10-мин точек |
| gaps | T1 2024-05-18→07-17 выбросить (или T2 как прокси); часы с <4 сэмплов → NaN; никаких ffill/interpolate таргета |
| выход | clip [0.01, 0.99]; cap T2 фитить по последним ~3 месяцам (0.97→0.99 в 2026Q1) |

OpenOA-аналоги: range_flag, window_range_flag, bin_filter, unresponsive_flag, std_range_flag, cluster_mahalanobis_2d; кривые IEC binned / logistic_5_parametric / gam_3param ([openoa](https://openoa.readthedocs.io/en/main/api/utils.html)).

### 4.5 Протокол оценки

- Rolling-origin backtest, зеркалящий тест: ежедневный выпуск, горизонты h=1..48, только прогоны с init до issue time. Holdouts: **Feb 2024, Feb 2025, Jan 2026** (ветреная и тихая зимы). Feb 2026 не трогать.
- Метрики по Madsen: nBIAS(k), nMAE(k), nRMSE(k), SDE(k) на каждый lead и по блокам h1–24 / h25–48; skill = 100·(MAE_pers − MAE_model)/MAE_pers; pinball loss и покрытие P10–P90; reliability diagram; error-vs-lead; пример недели.
- Считать только часы с данными SCADA (n≥4); отдельно — без outage-часов (остаток < −0.3), чтобы показать weather-explainable skill vs raw.
- Таблица бейзлайнов рядом (§2.5). Точечный прогноз — медиана для MAE, среднее для RMSE: уточнить у организаторов.
- Объяснимость: feature importance + SHAP, scatter raw vs clean кривой, NWP-vs-nacelle bias plot.

### 4.6 Ожидаемая точность

| Источник оценки | 24–48 ч, одиночная ВЭС |
|---|---|
| Коммерческие провайдеры ([GET.transform](https://www.get-transform.eu/wp-content/uploads/2024/01/GET.transform-Brief_VRE-Forecasting-Solar-Wind.pdf)) | MAE 7–19% capacity (ср. ~12%), RMSE 10–20% (ср. ~13.5%); ≥18% RMSE в сложном рельефе |
| Европейские single-farm | сезонный day-ahead RMSE 7–13%, MAE 4–8% (зима хуже) |
| Обзор по горизонтам | NMAE 2.5–5.5% @6 ч, 6–9.5% @12 ч, 10–17% @day-ahead; [NREL](https://docs.nrel.gov/docs/fy11osti/50814.pdf) 15–20% MAE single plant |
| Цель по литературе | nMAE 10–15% / nRMSE 13–18%; <10% — отлично |
| Оценка EDA для этой площадки | ERA5-кривая 0.177; с реальным day-ahead NWP **0.18–0.25** (одиночная турбина без сглаживания, коридор 1.39× ERA5) |

---

## 5. Агентная архитектура

**Фреймворк:** Pydantic AI 2.33 — `Agent('anthropic:claude-opus-5', deps_type=Deps, output_type=IssueDecision)`, `pip install "pydantic-ai-slim[anthropic]"`, typed tools `@agent.tool`, `AnthropicModelSettings(anthropic_thinking={'type':'adaptive'})`, `TestModel`/`FunctionModel` + `models.ALLOW_MODEL_REQUESTS=False` для CI без ключа, `Agent.instrument_all()` (OTel) ([anthropic](https://pydantic.dev/docs/ai/models/anthropic/), [testing](https://pydantic.dev/docs/ai/testing/)); на нём построен [TimeCopilot](https://github.com/TimeCopilot/timecopilot). План B — голый Anthropic SDK `@beta_tool` + `client.beta.messages.tool_runner` ([docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner)). Альтернатива — LangGraph (`create_agent`, SqliteSaver; pin langgraph≥1.0.10, langgraph-checkpoint-sqlite≥3.0.1 из-за CVE-2025-67644 / CVE-2026-28277; донор паттернов [windward](https://github.com/fborbon/windward)). Не для ядра: Claude Agent SDK (subprocess, bash/fs surface), CrewAI, OpenAI Agents SDK (через LiteLLM), smolagents (не подтверждено).

**Что код / что LLM:**

| Код (детерминированно) | LLM (планировщик) |
|---|---|
| fetch, кэш, feature engineering, inference, метрики, хранение, расписание | план выпуска (какие прогоны/модели), gate по DataQualityReport (accept / fallback / abort), решение о bias-correction и re-issue, интерпретация spread и остатков, отчёт на русском, memory-заметка. Каждое решение — в `trace.jsonl` |

**Tools:** `get_clock`, `fetch_nwp_forecast` (Single Runs ecmwf_ifs, последний прогон с init+7 ч ≤ issue), `fetch_nwp_ensemble` (Previous Runs day1/day2, 3+ модели), `fetch_scada_history` (строки ≤ issue time), `check_data_quality`, `prepare_features` (одна схема train/infer), `predict_power` (LightGBM quantiles, T1/T2), `compare_with_previous`, `evaluate_forecast`, `detect_drift` (none | bias_correct | retrain), `apply_bias_correction` (rolling_bias_7d), `save_forecast` (SQLite + `runs/<issue>/forecast.csv`), `read_memory`/`write_memory`, `write_report`. `UsageLimits(request_limit=25)`.

**As-of clock / anti-leakage:** `allowed_runs = [r for r in runs if r.init + 7h <= issue_time]` (HRES) / +9 ч (ifs025); unit-test, что ни одно значение не из прогона после issue time.

**Триггеры (event queue):** SCHEDULED_ISSUE (по умолчанию 08:00 UTC, прогон 00z; опц. 14/20/02 UTC); NWP_RUN каждые 6 ч (00/06/12/18 + лаг); SCADA_BATCH ежечасно (только dev-окно); RESIDUAL_ALERT при |z| остатков за 6 ч > 2.5; DIVERGENCE_ALERT при расхождении 24-ч среднего ветра нового прогона с последним выпущенным > 1.5 м/с. Агент решает, менять ли опубликованный прогноз.

**Два окна одним кодом:** `--window dev` (Jan 2026, факты есть → evaluate/drift/residual демонстрируются) и `--window test` (2026-01-31..02-28, факты скрыты → триггеры NWP_RUN + divergence; пишет `submission/forecast_feb2026.csv`: issue_time, target_time, turbine, p10, p50, p90 (в research.json — power_p50; унифицировано с SQLite-схемой)).

**Без ключа:** `LLM_MODE=scripted` — ScriptedPlanner с тем же интерфейсом, теми же tool-вызовами и форматом трейса; `make verify` в scripted-режиме < 2 мин. Стоимость LLM (не подтверждено): claude-opus-5 $5/$25 за MTok, ≈$1.05/выпуск без кэша (~$0.5 с prompt caching), 58 выпусков ≈ $30–60 Opus / $12–25 Sonnet.

**Delivery:** uv Docker `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, Makefile (setup/data/train/backtest/dashboard/verify/docker), `.env.example` (ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_MODE, OPEN_METEO_CACHE_ONLY, ISSUE_HOURS_UTC, REISSUE_ON_NEW_RUN, SCADA_TZ_OFFSET_HOURS=6 (в .env.example из research.json стояло 5 до верификации TZ; 6 — подтверждённое значение)), SQLite `forecasts(issue_time, target_time, horizon_h, turbine, p10, p50, p90, model_version, nwp_run, source, created_at)`, дашборд Streamlit и/или static React по `runs/*.json`, revision plot (последовательные прогнозы на один target hour). Цитаты для README: TimeCopilot [2509.00616](https://arxiv.org/html/2509.00616v2), DCATS [2508.04231](https://arxiv.org/abs/2508.04231), CastFlow [2604.27840](https://arxiv.org/abs/2604.27840), обзор [2605.25141](https://arxiv.org/html/2605.25141v1), Anthropic [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

---

## 6. Рынок Казахстана и ценность

| Факт | Значение | Источник |
|---|---|---|
| Балансирующий рынок и Единый закупщик | в реальном режиме с 1 июля 2023 (до — имитация) | [kegoc.kz](https://www.kegoc.kz/ru/electric-power/) |
| Обязанность ВИЭ | почасовой суточный график Единому закупщику до **08:00 Астаны D-1** (= 03:00 UTC), Правила V1500010662 п.9; корректировки вверх до 2 ч до часа; договор передачи ответственности (Закон «Об электроэнергетике» ст. 15-10 п.15–16) | [zakon.uchet.kz](https://zakon.uchet.kz/rus/docs/V1500010662), [kodeksy-kz](https://kodeksy-kz.com/ka/ob_elektroenergetike/15-10.htm) |
| Коэффициенты небаланса (не подтверждено) | PPA после 1 июля 2023: недобор покупается по PPA × повышающий, избыток продаётся по PPA × понижающий; 1.0/1.0 для PPA 2023–2025, **1.3/0.7** для PPA после 12 апреля 2025 (~70 проектов, 2 ГВт); источники расходятся по 2024; внутри «допустимого отклонения» коэффициент 1.0, размер полосы не установлен; PPA до 2023 (Нурлы, Energia Semirechya) — 1.0 на весь срок | [inbusiness](https://inbusiness.kz/ru/last/kazahstan-utochnil-pravila-balansiruyushego-rynka-elektroenergii), [qazaqgreen](https://qazaqgreen.com/journal-qazaqgreen/expert-opinion/2005/) |
| Убыток Единого закупщика | **2.148 млрд KZT** чистого убытка на балансирующем рынке в 2024 (расходы 7.546 vs доходы 5.398 млрд), причина — небалансы ВИЭ, социализируется на оптовых потребителей | [inbusiness](https://inbusiness.kz/ru/news/edinyj-zakupshik-ushel-v-ubytok-iz-za-zelenoj-energii) |
| Небалансы ВИЭ 2022 (9 мес.) | ~1,751 ГВт·ч из 3,504 ГВт·ч выработки (~50%); среднее почасовое отклонение: **ветер 60.7%**, солнце 40.7%, гидро 22.9% | [qazaqgreen](https://qazaqgreen.com/journal-qazaqgreen/analitycs/864/) |
| Тарифы 2025 | Energia Semirechya 31.58 KZT/кВт·ч, First Wind Station 52.35, Samruk-Green solar 30.76 | [ar2024.samruk-energy.kz](https://ar2024.samruk-energy.kz/ru/kazakhstan-power-and-coal-markets.html) |
| Программа Samruk-Energo | AI/ML-система планирования выработки ВИЭ на SCADA/АСКУЭ + метео, цель **80% точности**, запуск конец 2026 — ровно этот кейс | [nationalbusiness.kz](https://nationalbusiness.kz/news/iskusstvenniy-intellekt-budet-sledit-za-kazahstanskoy-energetikoy-d4f009/), [inform.kz](https://www.inform.kz/ru/ii-povisit-tochnost-prognozov-virabotki-vie-do-80-v-kazahstane-8221b43c) |
| Масштаб | 172 объектов ВИЭ (71 ВЭС), 3.8+ ГВт; прогноз выработки ВИЭ 2026 — 8.8 ТВт·ч; Шелекский коридор 110+ МВт у той же группы | [inform.kz](https://www.inform.kz/ru/energiya-budushego-razvitie-i-potentsial-vie-4f8759) |

Арифметика ценности (не подтверждено, оценка): при 1.3/0.7 и тарифе ~31.6 KZT/кВт·ч каждый кВт·ч ошибки стоит ~9.5 KZT; ВЭС 60 МВт (~226 ГВт·ч/год) с 20% энерго-взвешенной ошибкой рискует ~430 млн KZT/год; сокращение ошибки вдвое ≈ 200 млн KZT/год. Нарратив для жюри: «ветер отклоняется на 60% почасово; агент целится в <15%; 2 млрд KZT/год социализированных потерь; drop-in для программы Samruk-Energo с целью 80%».

Каденс агента = каденс рынка: выпуск к 03:00 UTC на D-1 для 00–23 дня D (lead 21–45 ч), затем повторные выпуски на каждом новом прогоне NWP (00/06/12/18 UTC) — это и есть «повторный расчёт при обновлении входных данных».

---

## 7. Открытые вопросы

1. **Таймзона:** подтвердить у организаторов фиксированный UTC+6 (январь 2026 по ветру даёт −5.0..−5.5 ч, остальное — +6). В каком времени ожидаются метки сабмишена — UTC, UTC+6 (часы SCADA) или UTC+5 (официальное)? Скрытый факт Feb 2026 — на часах SCADA?
2. `Статистическое время` — начало или конец 10-мин окна (±5–10 мин).
3. Ступица 80 vs 90 м; какой уровень NWP главный — 80 / 100 / 120 м (ICON 80 м чуть лучше 100 м на Dec–Jan) — решать бэктестом.
4. **Конвенция issue time:** что считается «прогнозом на 31 января» — прогон 12Z D-1 (доступен 23:30 Алматы), 18Z (~05:30 следующего дня), смесь previous_day1, 08:00 UTC с 00z, или 03:00 UTC (дедлайн рынка)? Горизонт +1..+48 или только +24..+48? Один выпуск в день или intraday re-issues? Нужно решение команды и явная формулировка в README.
5. **Метрика и агрегация:** MAE / RMSE / nMAE / MAPE; по турбине, сумме или среднему; 10-мин или час; как считаются часы без SCADA (дневные дырки обслуживания) и часы простоя в Feb 2026. От этого зависит медиана vs среднее.
6. Формат сабмишена: колонки CSV, зона времени, 0..1 или кВт.
7. Примет ли жюри previous_dayN (скользящий набор прогонов) как «прогноз, доступный на момент», или нужен один прогон с явным init (Single Runs / сырой GRIB)? Достаточно ли Open-Meteo-only как «открытые источники» или сырой ECMWF/NOAA путь должен быть заглавным?
8. Open-Meteo: архивные API помечены Professional на pricing, но отвечают без ключа — приемлемость для хакатона; в любом случае коммитить кэш. Первая дата ecmwf_ifs 9 км в Previous Runs (null 2025-09-15, data 2025-10-15) — важно только если 9 км станет primary. `timezone=Asia/Almaty` для дат 2023 не тестировался (не нужен при UTC + −6 ч).
9. Соседние ~13 турбин в 0.3–1.1 км: работают? с какого времени? wake T1/T2 при западном ветре? Проверить остатки по годам и секторам.
10. Величина «допустимого отклонения»; какая когорта коэффициентов (1.0/1.0 vs 1.3/0.7) действует сейчас; подтвердить, что PPA Нурлы до июля 2023 (ввод 2020 → скорее 1.0).
11. Дыра T1 2024-05-18…07-17: выбросить или заполнить из T2; это простой или потеря данных? Риск плановых работ в Feb 2026 непрогнозируем — зафиксировать как ограничение.
12. Почему cap T2 сдвинулся 0.97 → 0.99 в 2026Q1 (перенормировка на nameplate? софт?) — влияет на потолок T2 в Feb 2026.
13. Ограничивает ли сетевой оператор станцию в тестовом месяце (curtailment) — нули в фактах будут непрогнозируемы.
14. Стратегия обучения до 2024-03 (нет lead-aligned архива): (a) только previous-runs 2024–2025, (b) pre-train на сшитом Historical Forecast 2023+ и fine-tune, (c) смешать с признаком source — решать на Feb 2025. Нужна ли lead-aware коррекция или хватит online bias-correction агента — после dev-метрик.
15. Наблюдения Malibay 36894 за Feb 2026 (Ogimet 403, NOAA ISD 2026 → 404) — только если используются лаговые obs.
16. Meteomatics / meteoblue: pin конкретного прогона через API не проверен — только при наличии платного аккаунта.
17. Коммерциализация: платный ключ Open-Meteo или self-hosting из `s3://openmeteo`; ECMWF/NOAA сырые данные остаются бесплатными.
18. Будут ли эксперты запускать со своим ANTHROPIC_API_KEY — если нет, scripted-режим становится primary path в «Проверке основного сценария», LLM-трейсы шипятся артефактами в репо.

# Решения

| Решение | Кто | Почему |
|---|---|---|
| **LOC-18: go** — train на Single Runs `ecmwf_ifs` (`data/nwp/single_runs_ecmwf_ifs_train.parquet`, 686/689 issue-дней 2024-03-14→2026-01-31: 06Z ×535, fallback 00Z ×151; пропуски 2025-08-05/07/09 — 400 или all-null у всех кандидатов; пропусков с 2024-08 — 0.55% < 5%) | Akylbek | Train/serve consistency: те же лиды 12–59 (00Z-fallback 18–65), что у dayahead-инференса. До 2025-10 архив 9 км — hindcast IFS Cycle 49R1 (доки Open-Meteo), с 2025-10-01 и в Feb 2026 — real-time open data. 714 сетевых вызовов, повтор с `OPEN_METEO_CACHE_ONLY=1` — 0 вызовов, тот же parquet. Отчёт по месяцам — `single_runs_ecmwf_ifs_train.manifest.json` |
| **LOC-11: P50 для MAE, mean для RMSE** — LightGBM quantile P10/P50/P90 + отдельный L2 mean; интервалы split-conformal, no crossing | Akylbek | На Jan 2026 coverage P10–P90 = 84.7–85.7%; P50 MAE 0.175/0.179 и не хуже v1 более чем на 0.01. Mean снижает RMSE на обеих турбинах. `POINT_ESTIMATE=cost` зарезервирован за LOC-31. |

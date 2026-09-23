# LOC-10 — LightGBM v1

Leak-safe point-model spike on pooled T1/T2 rows. The primary features come from one explicit ECMWF IFS Single Run per issue; Previous Runs features use day1 only after that underlying cycle is public, otherwise day2. February 2025 and January 2026 are excluded from fitting.

The published point estimate is a conservative 40% LightGBM / 60% v0 blend. This keeps the physical MOS + power-curve anchor while the tree adds multi-model, direction, density, calendar and lead corrections.

| Window | Turbine | Model | n | MAE | RMSE | Bias | Skill vs v0 |
|---|---|---|---:|---:|---:|---:|---:|
| feb2025 | T1 | `lightgbm-v1` | 1,332 | 0.162 | 0.233 | +0.025 | +3.8% |
| feb2025 | T1 | `mos-curve-v0` | 1,332 | 0.169 | 0.240 | +0.014 | +0.0% |
| feb2025 | T2 | `lightgbm-v1` | 1,332 | 0.186 | 0.279 | +0.060 | +1.6% |
| feb2025 | T2 | `mos-curve-v0` | 1,332 | 0.189 | 0.279 | +0.050 | +0.0% |
| jan2026 | T1 | `lightgbm-v1` | 1,464 | 0.171 | 0.236 | +0.065 | +1.4% |
| jan2026 | T1 | `mos-curve-v0` | 1,464 | 0.174 | 0.237 | +0.042 | +0.0% |
| jan2026 | T2 | `lightgbm-v1` | 1,464 | 0.175 | 0.241 | +0.070 | +1.1% |
| jan2026 | T2 | `mos-curve-v0` | 1,464 | 0.177 | 0.240 | +0.047 | +0.0% |

The report also contains h1–24 / h25–48 and weather-explainable slices. All values are normalized by turbine nameplate capacity.

## Top feature importance

| Feature | Gain share |
|---|---:|
| `ensemble_ws100_mean` | 53.4% |
| `ws100_lead1` | 6.8% |
| `prev_ecmwf_ifs025_ws100` | 4.6% |
| `target_doy_cos` | 4.4% |
| `target_doy_sin` | 4.3% |
| `surface_pressure` | 3.4% |
| `density_normalized_ws100` | 2.8% |
| `prev_icon_global_ws100` | 2.1% |
| `wind_dir_sin` | 1.6% |
| `air_density` | 1.5% |
| `shear_100_10` | 1.5% |
| `wind_u100` | 1.4% |

## Reproduce

```bash
uv run --frozen python -m windagent.model.v1
```

This command is offline; it reads only committed Parquet artifacts.

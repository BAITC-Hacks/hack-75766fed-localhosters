# Synthetic inputs

`nwp/` contains hand-generated, deterministic weather fixtures for 31 January 2026.
They are **not downloaded forecasts**. The 12Z fixture raises wind by 2 m/s to exercise
the revision trigger at 20:00 UTC (12Z initialization + eight-hour availability lag).
The demo curve is not trained. No accuracy metrics or calibrated quantiles are claimed.

Real adapters must return the schema in `windagent/schemas.py` with `data_kind=archive`.
Production mode rejects these fixtures rather than silently falling back to them.

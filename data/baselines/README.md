# Weather inputs for LOC-9

`era5_ws100.parquet` is the compact projection of the verified Open-Meteo Archive
response with `models=era5`, turbine T1 coordinates, `timezone=UTC`, and
`wind_speed_unit=ms`. It covers 2023-03-10 through 2026-01-31 (25,416 hours),
including the boundary hours required by 48-hour issue windows. SHA-256:
`2d8bb243e7f9fc183bd429a39c1f569cc405f509c2bcc8a0c7148e46ea420d61`.

`previous_runs_ws100.parquet` is the compact, evaluation-only projection of the
LOC-15 Open-Meteo Previous Runs cache for T1. It contains hourly UTC
`wind_speed_100m_previous_day1/day2` values for `icon_global` (2024-02-16 through
2026-02-28) and `ecmwf_ifs025` (2024-03-06 through 2026-02-28).

The source requests use turbine T1 coordinates 43.64515, 78.535604,
`timezone=UTC`, and `wind_speed_unit=ms`. The source branch keeps chunk-level raw
JSON, metadata, request keys, grids, and SHA-256 values; this 310,692-byte projection
keeps LOC-9 reproducible without duplicating that larger archive. SHA-256:
`38275f5ad1034c6b76bc508b5a439b9bd6ce6608b0c341ff0f5a8649d817bedb`.

from __future__ import annotations

import numpy as np

from windagent.eval.baselines import build_report


def _mae(report, window, baseline, *, model="", turbine="T1", scope="all"):
    row = report.loc[
        (report.window == window)
        & (report.turbine_id == turbine)
        & (report.baseline == baseline)
        & (report.model == model)
        & (report["mode"] == "all")
        & (report.scope == scope)
    ]
    assert len(row) == 1
    return float(row.mae.iloc[0])


def test_t1_acceptance_corridors_and_no_fake_feb_2024_nwp() -> None:
    report = build_report()
    assert 0.26 <= _mae(report, "Jan 2026", "constant_median") <= 0.28
    assert 0.29 <= _mae(report, "Feb 2025", "constant_median") <= 0.31
    assert 0.29 <= _mae(report, "Jan 2026", "month_hour_climatology") <= 0.35
    assert 0.36 <= _mae(report, "Jan 2026", "same_hour_yesterday") <= 0.41
    assert 0.20 <= _mae(
        report,
        "Feb 2025",
        "previous_runs_refit_curve",
        model="ecmwf_ifs025",
        scope="h1-24",
    ) <= 0.22
    assert 0.20 <= _mae(
        report,
        "Jan 2026",
        "previous_runs_refit_curve",
        model="icon_global",
        scope="h25-48",
    ) <= 0.23
    assert 0.19 <= _mae(report, "Jan 2026", "era5_fixed_scada_curve") <= 0.21
    assert 0.15 <= _mae(report, "Jan 2026", "era5_refit_lomo") <= 0.21
    assert 0.025 <= _mae(report, "Jan 2026", "perfect_wind") <= 0.04
    feb_2024_nwp = report.loc[
        (report.window == "Feb 2024")
        & (report.baseline == "previous_runs_refit_curve")
    ]
    assert feb_2024_nwp.empty


def test_right_label_evaluates_the_same_intervals() -> None:
    left = build_report(label="left")
    right = build_report(label="right")
    keys = ["window", "turbine_id", "baseline", "model", "mode", "scope"]
    left = left.sort_values(keys).reset_index(drop=True)
    right = right.sort_values(keys).reset_index(drop=True)
    assert left[keys].equals(right[keys])
    assert np.allclose(left.mae, right.mae, equal_nan=True)

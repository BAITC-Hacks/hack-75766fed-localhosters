from __future__ import annotations

import numpy as np
import pandas as pd

from windagent.config import MIN_SAMPLES_PER_HOUR
from windagent.data.scada import FLAG_COLUMNS, load_hourly_dataset, load_raw, power_curve


def test_canonical_shape_time_and_gaps() -> None:
    df = load_hourly_dataset()
    assert len(df) == 25_392 * 2
    assert str(df["ts"].dt.tz) == "UTC"
    assert set(df["turbine_id"]) == {"T1", "T2"}
    assert not df.duplicated(["ts", "turbine_id"]).any()
    assert df.groupby("turbine_id")["n"].apply(lambda s: int(s.eq(0).sum())).to_dict() == {
        "T1": 1_629,
        "T2": 388,
    }
    assert df.loc[df["n"] < MIN_SAMPLES_PER_HOUR, ["ws", "p", "temp"]].isna().all().all()


def test_quality_rates_match_research_contract() -> None:
    df = load_hourly_dataset()
    rates = df.groupby("turbine_id", observed=True)[list(FLAG_COLUMNS[:-1])].mean()
    assert (rates <= 0.02).all().all()
    assert rates["outage"].between(0.006, 0.012).all()


def test_verified_power_curve_sanity() -> None:
    df = load_hourly_dataset()
    valid = df.dropna(subset=["ws", "p"])
    prediction = power_curve(valid["ws"])
    mae = float(np.mean(np.abs(valid["p"] - prediction)))
    residual = valid["p"].to_numpy() - prediction
    r2 = 1.0 - float(np.sum(residual**2) / np.sum((valid["p"] - valid["p"].mean()) ** 2))
    assert 0.025 <= mae <= 0.035
    assert r2 >= 0.96


def test_no_clock_change_at_march_2024_boundary() -> None:
    for turbine in ("T1", "T2"):
        raw = load_raw(turbine, utc=False)
        boundary = raw.loc["2024-02-29 22:00":"2024-03-01 02:00"]
        assert len(boundary) == 25
        assert not raw.index.duplicated().any()
        assert boundary.index.to_series().diff().dropna().eq(pd.Timedelta(minutes=10)).all()


def test_timezone_proof_artifact_meets_acceptance_bounds() -> None:
    results = pd.read_csv("data/tz_reference/tz_xcorr_results.csv")
    keys = ["source", "turbine_id", "window"]
    assert results.groupby(keys).ngroups == 8
    for _, group in results.groupby(keys):
        peak_lag = float(group.loc[group["r"].idxmax(), "lag_h"])
        r5 = float(group.loc[np.isclose(group["lag_h"], 5), "r"].iloc[0])
        r6 = float(group.loc[np.isclose(group["lag_h"], 6), "r"].iloc[0])
        assert 5.8 <= peak_lag <= 6.2
        assert r6 > r5

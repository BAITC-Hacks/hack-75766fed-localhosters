"""Leak-тест as-of конвенции: ни одно значение прогноза не опирается на ран, недоступный на момент выпуска."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from windagent import clock

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def test_per_cycle_availability():
    d = datetime(2026, 1, 31, tzinfo=UTC)
    assert clock.available_at(d.replace(hour=0)) == d.replace(hour=8)
    assert clock.available_at(d.replace(hour=6)) == d.replace(hour=13)
    assert clock.available_at(d.replace(hour=12)) == d.replace(hour=20)
    assert clock.available_at(d.replace(hour=18)) == d + timedelta(days=1, hours=1)


def test_12z_not_available_at_19z_but_at_20z():
    run12 = datetime(2026, 1, 31, 12, tzinfo=UTC)
    assert not clock.is_available(run12, datetime(2026, 1, 31, 19, tzinfo=UTC))
    assert clock.is_available(run12, datetime(2026, 1, 31, 20, tzinfo=UTC))


def test_dayahead_issue_picks_06z():
    runs = [datetime(2026, 1, 31, h, tzinfo=UTC) for h in (0, 6, 12, 18)]
    issue = clock.issue_time_for_day(datetime(2026, 2, 1).date())
    assert issue == datetime(2026, 1, 31, 18, tzinfo=UTC)
    assert clock.latest_available_run(issue, runs) == runs[1]
    assert clock.latest_available_run(issue + timedelta(hours=2), runs) == runs[2]


def test_injected_late_run_rejected():
    issue = datetime(2026, 1, 31, 18, tzinfo=UTC)
    late = datetime(2026, 1, 31, 12, tzinfo=UTC)  # публичен только с 19:34
    assert clock.latest_available_run(issue, [late]) is None


def test_bad_cycle_rejected():
    with pytest.raises(ValueError):
        clock.available_at(datetime(2026, 1, 31, 3, tzinfo=UTC))


@pytest.mark.parametrize("csv", sorted((ROOT / "submission").glob("forecast_*_dayahead_*.csv")))
def test_submission_has_no_leakage(csv: Path):
    df = pd.read_csv(csv)
    issue = pd.to_datetime(df.issue_time_utc, utc=True)
    run = pd.to_datetime(df.nwp_run_init_utc, utc=True)
    target = pd.to_datetime(df.target_time_utc, utc=True)
    lag = run.dt.hour.map(clock.AVAIL_LAG_H)
    assert lag.notna().all(), "run cycle outside 00/06/12/18Z"
    assert ((run + pd.to_timedelta(lag, unit="h")) <= issue).all(), "run used before it was public"
    assert (target >= issue).all(), "target before issue time"
    assert ((target - issue).dt.total_seconds() / 3600 == df.lead_h).all()
    assert ((target - run).dt.total_seconds() / 3600 == df.nwp_lead_h).all()
    assert df.groupby(["issue_time_utc", "turbine"]).size().eq(48).all()


def test_predict_path_has_no_analysis_sources():
    """В predict-пути нет Historical Forecast / Archive / ERA5 (near-analysis) — только as-issued раны."""
    banned = re.compile(r"historical-forecast|archive-api|era5|best_match", re.I)
    for path in [ROOT / "windagent/backtest.py", ROOT / "windagent/clock.py", *(ROOT / "windagent/model").glob("*.py")]:
        code = "\n".join(line for line in path.read_text().splitlines() if not line.strip().startswith(("#", '"""')))
        assert not banned.search(code), f"analysis source referenced in {path.name}"

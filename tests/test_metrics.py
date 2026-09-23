from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from windagent.eval.metrics import (
    by_lead_block,
    evaluate_forecast,
    interval_coverage,
    interval_start,
    pinball_loss,
    skill_score,
)


def test_scalar_metrics_and_interval_label() -> None:
    actual = [0.0, 0.5, 1.0]
    predicted = [0.1, 0.4, 0.8]
    reference = [0.0, 0.0, 0.0]
    assert skill_score(actual, predicted, reference) == pytest.approx(73.3333333333)
    assert pinball_loss(actual, predicted, 0.5) == pytest.approx(0.0666666667)
    assert interval_coverage(actual, [0.0, 0.3, 0.9], [0.2, 0.7, 1.0]) == 1.0
    right = pd.date_range("2026-01-01 01:00", periods=2, freq="h", tz="UTC")
    expected = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    assert interval_start(right, label="right").equals(expected)


def test_evaluate_per_lead_blocks_modes_and_quantiles() -> None:
    frame = pd.DataFrame(
        {
            "lead_h": np.tile(np.arange(1, 49), 2),
            "actual": 0.5,
            "p10": 0.3,
            "p50": 0.4,
            "p90": 0.7,
            "outage": False,
            "is_clean": True,
        }
    )
    frame.loc[0, ["outage", "is_clean"]] = [True, False]
    all_metrics = evaluate_forecast(frame, mode="all")
    assert len(all_metrics) == 51
    assert int(all_metrics.loc[all_metrics.scope == "all", "n"].iloc[0]) == 96
    assert all_metrics.loc[all_metrics.scope == "h1-24", "nmae"].iloc[0] == pytest.approx(0.1)
    assert all_metrics.loc[all_metrics.scope == "all", "coverage_p10_p90"].iloc[0] == 1.0
    clean = evaluate_forecast(frame, mode="weather_explainable")
    assert int(clean.loc[clean.scope == "all", "n"].iloc[0]) == 95


def test_evaluate_rejects_unknown_contract_values() -> None:
    frame = pd.DataFrame({"lead_h": [49], "actual": [0.0], "p50": [0.0]})
    with pytest.raises(ValueError, match="1..48"):
        evaluate_forecast(frame)
    with pytest.raises(ValueError, match="mode"):
        evaluate_forecast(frame.assign(lead_h=1), mode="operational")


def test_loc17_zero_based_backtest_adapter() -> None:
    frame = pd.DataFrame(
        {
            "turbine": "T1",
            "lead_h": np.arange(48),
            "actual": 0.5,
            "p50": 0.4,
        }
    )
    result = by_lead_block(frame, "p50")
    assert result.set_index("block")["n"].to_dict() == {
        "h1_24": 24,
        "h25_48": 24,
        "all": 48,
    }
    assert np.allclose(result["mae"], 0.1)

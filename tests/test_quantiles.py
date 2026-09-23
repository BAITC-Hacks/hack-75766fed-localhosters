import pandas as pd

from windagent.config import Settings
from windagent.model import quantiles, serve, v1


def test_committed_quantile_models_match_feature_contract():
    models, metadata = serve.load_quantile_models()

    assert metadata["model_version"] == quantiles.MODEL_VERSION
    assert metadata["features"] == list(v1.FEATURES)
    assert set(models) == {"p10", "p50", "p90", "mean"}
    assert all(model.feature_name() == list(v1.FEATURES) for model in models.values())
    assert metadata["quantiles"] == {"p10": 0.1, "p50": 0.5, "p90": 0.9}


def test_holdout_report_meets_loc11_acceptance_criteria():
    report = pd.read_csv(quantiles.REPORT_PATH)
    summary = report.loc[(report["mode"] == "all") & (report["scope"] == "all")]
    median = summary.loc[summary["point_estimate"] == "median"]
    mean = summary.loc[summary["point_estimate"] == "mean"]

    january_coverage = median.loc[
        median["window"] == "jan2026", "coverage_p10_p90"
    ]
    assert january_coverage.between(0.75, 0.90).all()

    point_v1 = pd.read_csv(v1.REPORT_PATH)
    point_v1 = point_v1.loc[
        (point_v1["model"] == v1.MODEL_VERSION)
        & (point_v1["mode"] == "all")
        & (point_v1["scope"] == "all"),
        ["window", "turbine_id", "nmae"],
    ]
    comparison = median.merge(
        point_v1, on=["window", "turbine_id"], suffixes=("_p50", "_v1")
    )
    assert (comparison["nmae_p50"] <= comparison["nmae_v1"] + 0.01).all()

    points = median.merge(
        mean,
        on=["window", "turbine_id", "mode", "scope"],
        suffixes=("_median", "_mean"),
    )
    assert (points["nmae_median"] < points["nmae_mean"]).all()
    assert (points["nrmse_mean"] < points["nrmse_median"]).all()


def test_cost_point_estimate_is_reserved_for_loc31(monkeypatch):
    monkeypatch.setenv("POINT_ESTIMATE", "cost")
    assert Settings.from_env().point_estimate == "cost"

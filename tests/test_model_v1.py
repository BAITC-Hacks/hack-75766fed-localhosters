import lightgbm as lgb
import numpy as np
import pandas as pd

from windagent.model import v1


def test_previous_runs_values_obey_publication_lag():
    rows = pd.DataFrame(
        {
            "issue_day": pd.to_datetime(["2025-01-10", "2025-01-10"]),
            "valid_utc": pd.to_datetime(
                ["2025-01-11T06:00Z", "2025-01-11T12:00Z"], utc=True
            ),
        }
    )
    previous = pd.DataFrame(
        {
            "model": ["ecmwf_ifs025", "ecmwf_ifs025"],
            "valid_utc": rows["valid_utc"],
            "ws100_previous_day1": [1.0, 2.0],
            "ws100_previous_day2": [10.0, 20.0],
        }
    )

    values, ages = v1._select_previous_run(
        rows,
        previous,
        model="ecmwf_ifs025",
        availability_lag_h=8,
    )

    # At the 18Z issue, the prior-day 06Z run was public at 14Z, while the
    # prior-day 12Z run is not public until 20Z and must fall back to day2.
    np.testing.assert_array_equal(values, [1.0, 20.0])
    np.testing.assert_array_equal(ages, [1.0, 2.0])


def test_feature_dataset_is_pooled_aligned_and_excludes_holdouts_from_fit():
    frame = v1.build_dataset()

    assert set(v1.FEATURES) <= set(frame)
    assert set(frame["turbine_id"]) == {"T1", "T2"}
    assert frame["forecast_lead_h"].between(1, 48).all()
    counts = frame.groupby(["issue_day", "turbine_id"], observed=True).size()
    assert counts.eq(48).all()

    training = v1.training_rows(frame)
    assert training.any()
    for holdout in v1.HOLDOUTS:
        assert not (training & v1._holdout_mask(frame["issue_day"], holdout)).any()


def test_small_model_returns_bounded_predictions():
    frame = v1.build_dataset()
    model = v1.fit_model(frame, num_iterations=5)
    sample = frame.loc[v1._holdout_mask(frame["issue_day"], v1.HOLDOUTS[0])].head(32)

    prediction = v1.predict(model, sample)

    assert prediction.shape == (32,)
    assert np.isfinite(prediction).all()
    assert ((0 <= prediction) & (prediction <= 1)).all()


def test_committed_model_artifact_has_canonical_feature_order():
    model = lgb.Booster(model_file=str(v1.MODEL_PATH))

    assert model.feature_name() == list(v1.FEATURES)

"""LOC-12 artifact contract: models/lgbm_v1.pkl + models/metadata.json -> predict(features) -> p10/p50/p90.

The pickle is a dict written by the training code (LOC-10, quantiles LOC-11):
    {"model_version": str, "features": FEATURES, "p50": <.predict(X)>,
     "p10": <.predict(X)> | None, "p90": <.predict(X)> | None,
     # used when p10/p90 are None: empirical residual quantiles per p50 bin, as in v0
     "bins": [...], "resid_q10": [...], "resid_q90": [...]}
lightgbm is imported only by unpickling, so `from windagent.model import FEATURES` works without it.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from windagent.model.schema import CATEGORICAL, FEATURES, SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = ROOT / "models" / "lgbm_v1.pkl"
METADATA_PATH = ROOT / "models" / "metadata.json"
P_MIN, P_MAX = 0.01, 0.99

_cache: dict[Path, dict] = {}


def features_hash(features=FEATURES) -> str:
    return hashlib.sha256(json.dumps(list(features)).encode()).hexdigest()[:12]


def load_artifact(path: Path = ARTIFACT_PATH) -> dict:
    path = Path(path)
    if path not in _cache:
        if not path.exists():
            raise FileNotFoundError(f"MODEL_NOT_FOUND: {path} (train it in LOC-10)")
        with path.open("rb") as fh:
            artifact = pickle.load(fh)  # noqa: S301 (own artifact from models/)
        if list(artifact.get("features", [])) != FEATURES:
            raise ValueError(
                f"SCHEMA_MISMATCH: {path} features hash {features_hash(artifact.get('features', []))} "
                f"!= FEATURES {features_hash()}"
            )
        _cache[path] = artifact
    return _cache[path]


def _matrix(features: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in FEATURES if c not in features.columns]
    if missing:
        raise ValueError(f"INVALID_INPUT: features lack {missing}; build them with build_features()")
    X = features[FEATURES].copy()
    for column in CATEGORICAL:
        X[column] = X[column].astype("int64")
    return X


def predict(features: pd.DataFrame, artifact: dict | Path | None = None) -> pd.DataFrame:
    """features[FEATURES] -> DataFrame[p10, p50, p90] on the same index; p10 <= p50 <= p90, p50 in [0.01, 0.99]."""
    art = artifact if isinstance(artifact, dict) else load_artifact(artifact or ARTIFACT_PATH)
    X = _matrix(features)
    p50 = np.clip(np.asarray(art["p50"].predict(X), dtype=float), P_MIN, P_MAX)
    if art.get("p10") is not None and art.get("p90") is not None:
        p10 = np.asarray(art["p10"].predict(X), dtype=float)
        p90 = np.asarray(art["p90"].predict(X), dtype=float)
    else:
        bins = art["bins"]
        idx = np.clip(np.digitize(p50, bins) - 1, 0, len(bins) - 2)
        p10 = p50 + np.asarray(art["resid_q10"])[idx]
        p90 = p50 + np.asarray(art["resid_q90"])[idx]
    p10 = np.minimum(np.clip(p10, 0.0, 1.0), p50)
    p90 = np.maximum(np.clip(p90, 0.0, 1.0), p50)
    return pd.DataFrame({"p10": p10, "p50": p50, "p90": p90}, index=features.index)


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_metadata(*, model_version: str, train_range: tuple[str, str], holdout_metrics: dict,
                   params: dict | None = None, excluded: list[str] | None = None,
                   path: Path = METADATA_PATH, **extra) -> dict:
    """models/metadata.json for a trained artifact; call from the training notebook/script."""
    try:
        import lightgbm
        lgbm_version = lightgbm.__version__
    except ImportError:
        lgbm_version = None
    meta = {
        "schema_version": SCHEMA_VERSION,
        "model_version": model_version,
        "features": FEATURES,
        "features_hash": features_hash(),
        "categorical": CATEGORICAL,
        "train_range_utc": list(train_range),
        "excluded_periods": excluded or [],
        "holdout_metrics": holdout_metrics,
        "params": params or {},
        "lightgbm_version": lgbm_version,
        "git_sha": git_sha(),
        "built_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **extra,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    return meta

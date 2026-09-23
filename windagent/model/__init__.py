"""Модели прогноза мощности. Контракт (LOC-12): predict_power(request) -> PowerForecast-словарь.

    from windagent.model import FEATURES, build_features, predict
"""

from windagent.model.artifact import predict, write_metadata
from windagent.model.schema import FEATURES, KEYS, build_features

__all__ = ["FEATURES", "KEYS", "build_features", "predict", "write_metadata"]

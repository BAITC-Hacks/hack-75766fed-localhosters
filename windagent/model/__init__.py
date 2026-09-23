"""Модели прогноза мощности. Контракт (LOC-12): predict_power(request) -> PowerForecast-словарь.

    from windagent.model import FEATURES, build_features, predict
"""


def __getattr__(name):
    # Lazy: v1 imports lightgbm and `from windagent.model import v0`; importing it eagerly here would cycle.
    if name in ("FEATURES", "KEYS", "build_features"):
        from windagent.model import schema
        return getattr(schema, name)
    if name == "predict":
        from windagent.model.serve import predict
        return predict
    raise AttributeError(name)


__all__ = ["FEATURES", "KEYS", "build_features", "predict"]

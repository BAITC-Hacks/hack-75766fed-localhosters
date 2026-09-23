"""Загрузчик SCADA двух турбин (task context/*.csv): 10-мин сырьё -> UTC -> hourly -> long-формат.

Провенанс: eda/load.py ресёрч-агента (2026-09-23); пути сделаны относительными к корню репо,
добавлены конвертация в UTC и long-формат по контракту LOC-8.

Факты:
  * колонки: ID, Статистическое время, Средняя скорость ветра(m/s), Нормализованная активная мощность,
    Средняя температура окружающей среды(°C) -> ts, ws, p, temp;
  * 'Статистическое время' — ФИКСИРОВАННЫЙ UTC+6 на весь период (не Asia/Almaty: SCADA-часы не перешли
    на UTC+5 1 марта 2024 — кросс-корреляция с ERA5, см. tz_check.py). POSIX-зона Etc/GMT-6 == UTC+6;
  * период 2023-03-11 00:00 -> 2026-01-31 23:50 по часам файла, февраля 2026 в файлах нет;
  * пустых ячеек нет, дублей ts нет; T1 без данных 2024-05-18 -> 2024-07-17.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
CTX = REPO / "task context"
FILES = {
    "T1": CTX / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 1.csv",
    "T2": CTX / "Dataset HackAlemAI для участников 11.03.2023-28.02.2026 - turbine 2.csv",
}
COORDS = {"T1": (43.64515, 78.535604), "T2": (43.643198, 78.538828)}
RENAME = {
    "Статистическое время": "ts",
    "Средняя скорость ветра(m/s)": "ws",
    "Нормализованная активная мощность": "p",
    "Средняя температура окружающей среды(°C)": "temp",
}
SCADA_TZ = "Etc/GMT-6"  # фиксированный UTC+6; utc = ts_file - 6h


def _key(turbine) -> str:
    t = str(turbine).upper()
    return t if t.startswith("T") else f"T{t}"


def load_raw(turbine="T1", utc: bool = True) -> pd.DataFrame:
    """10-мин строки, индекс ts, колонки ws/p/temp, отсортировано, дубли ts убраны (keep last).
    utc=True -> индекс tz-aware UTC (Etc/GMT-6 -> UTC); utc=False -> naive часы файла (для tz-проверок)."""
    t = _key(turbine)
    df = pd.read_csv(FILES[t], encoding="utf-8").rename(columns=RENAME).drop(columns=["ID"])
    df["ts"] = pd.to_datetime(df["ts"], format="%Y-%m-%d %H:%M:%S")
    df = df.sort_values("ts")
    dup = int(df["ts"].duplicated(keep="last").sum())
    if dup:
        df = df[~df["ts"].duplicated(keep="last")]
    if utc:
        df["ts"] = df["ts"].dt.tz_localize(SCADA_TZ).dt.tz_convert("UTC")
    df = df.set_index("ts")
    df.attrs.update(duplicates_dropped=dup, turbine_id=t, utc=utc)
    return df


def to_hourly(df: pd.DataFrame, min_samples: int = 4, full_range: bool = True) -> pd.DataFrame:
    """10-мин -> часовые средние (label='left', closed='left': час 10:00 = среднее 10:00..10:50).
    n — число 10-мин отсчётов в часе; при n < min_samples ws/p/temp -> NaN. Таргет не интерполируется.
    full_range=True -> полная почасовая сетка от первого до последнего часа (пустые часы с n=0)."""
    g = df.resample("1h", label="left", closed="left")
    h = g[["ws", "p", "temp"]].mean()
    h["n"] = g["p"].count()
    if full_range:
        idx = pd.date_range(df.index.min().floor("h"), df.index.max().floor("h"), freq="1h")
        h = h.reindex(idx)
        h.index.name = "ts"
        h["n"] = h["n"].fillna(0).astype(int)
    h.loc[h["n"] < min_samples, ["ws", "p", "temp"]] = np.nan
    h.attrs.update(df.attrs)
    return h


def load_hourly(turbine="T1", min_samples: int = 4) -> pd.DataFrame:
    return to_hourly(load_raw(turbine, utc=True), min_samples=min_samples)


def load_hourly_long(min_samples: int = 4) -> pd.DataFrame:
    """Обе турбины, long-формат: turbine_id, ts (UTC), ws, p, temp, n."""
    parts = []
    for t in FILES:
        h = load_hourly(t, min_samples=min_samples).reset_index()
        h.insert(0, "turbine_id", t)
        parts.append(h)
    return pd.concat(parts, ignore_index=True)


if __name__ == "__main__":
    for t in FILES:
        raw = load_raw(t)
        h = to_hourly(raw)
        print(f"{t}: raw {raw.shape} dup_dropped={raw.attrs['duplicates_dropped']} "
              f"{raw.index.min()} .. {raw.index.max()} (UTC)")
        print(f"    hourly {h.shape}; n distribution {h['n'].value_counts().sort_index().to_dict()}; "
              f"hours with NaN target {int(h['p'].isna().sum())}")
    long = load_hourly_long()
    print(f"long: {long.shape} columns={list(long.columns)}")
    print(long.head(3).to_string(index=False))

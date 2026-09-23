"""Клиент Open-Meteo для архивных прогнозов (as-issued) и реанализа по координатам ВЭС.

Провенанс: собран из scratch-скриптов ресёрч-агента archived_wx.py + omclient.py (2026-09-23),
все эндпоинты и семантика lead time проверены живыми вызовами в тот же день (см. research/README.md).

Функции:
  om_get()              GET с retry на 429/5xx и on-disk JSON-кешем data/nwp_cache/<endpoint>/...
  previous_runs()       Previous Runs API: <var>_previous_day1/day2 — as-issued, lead 24–29 / 48–53 ч
  single_run()          Single Runs API: полный горизонт одного рана (run_init_utc + lead_h) — as-issued
  archive_era5()        Archive API, models=era5 — реанализ, ТОЛЬКО train/eval
  historical_forecast() Historical Forecast API — НЕ as-issued (склейка lead 0–5 ч), ТОЛЬКО train
  hourly_df()           json -> DataFrame с tz-aware UTC-индексом, проверка единиц (m/s)

Всегда timezone=UTC и wind_speed_unit=ms (дефолт API — km/h). Сеть не нужна, если ответ уже в кеше;
OPEN_METEO_CACHE_ONLY=1 запрещает сеть: cache miss -> CacheMiss с путём ключа.
Лимиты free tier: 600/мин, 5 000/ч, 10 000/день (weighted: >10 переменных или >2 недель = несколько вызовов).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO / "data" / "nwp_cache"
CACHE_ONLY = os.environ.get("OPEN_METEO_CACHE_ONLY", "").strip().lower() not in ("", "0", "false", "no")

# Координаты турбин (~300 м друг от друга). Для ecmwf_ifs 9 km обе попадают в один грид-пойнт 43.620384/78.47891,
# для 0.25°-моделей — 43.75/78.5 (ifs025, aifs, era5), 43.625/78.5 (icon), 43.638/78.516 (gfs).
TURBINES = {"T1": (43.64515, 78.535604), "T2": (43.643198, 78.538828)}
LAT, LON = TURBINES["T1"]

COMMON = {"timezone": "UTC", "wind_speed_unit": "ms"}

URL_PREVIOUS_RUNS = "https://previous-runs-api.open-meteo.com/v1/forecast"
URL_SINGLE_RUNS = "https://single-runs-api.open-meteo.com/v1/forecast"
URL_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
URL_HISTORICAL_FORECAST = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# Модели Previous Runs с полным покрытием Feb 2026 (0 null для ws100 day1/day2) и старт архива.
PREV_MODELS = {
    "ecmwf_ifs": "2025-10",             # IFS HRES 9 km
    "ecmwf_ifs025": "2024-03",
    "ecmwf_aifs025_single": "2025-03",
    "icon_global": "2024-03",
    "gfs_global": "2024-03",
}
# wind_gusts_10m у всех трёх ECMWF-моделей null (есть у icon_global / gfs_global).
WX_VARS = "wind_speed_100m,wind_speed_80m,wind_speed_10m,wind_direction_100m,wind_gusts_10m,temperature_2m,surface_pressure"
ERA5_VARS = "wind_speed_100m,wind_speed_10m,temperature_2m,wind_direction_100m,surface_pressure"

# Тестовое окно бэктеста: analysis-источники (ERA5, Historical Forecast) в нём — утечка.
TEST_WINDOW = ("2026-01-31", "2026-02-28")

_ENDPOINT_DIR = {
    "previous-runs-api": "previous_runs",
    "single-runs-api": "single_runs",
    "archive-api": "archive",
    "historical-forecast-api": "historical_forecast",
}


class CacheMiss(RuntimeError):
    """OPEN_METEO_CACHE_ONLY=1 и ответа нет в кеше."""


def cache_path(url: str, params: dict) -> Path:
    """Детерминированный путь кеша: data/nwp_cache/<endpoint>/<model>_<run|start_end>_<sha1[:10]>.json."""
    host = url.split("//", 1)[1].split(".", 1)[0]
    sub = _ENDPOINT_DIR.get(host, host)
    key = json.dumps(params, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    model = str(params.get("models", "default"))
    span = params.get("run") or f"{params.get('start_date', '')}_{params.get('end_date', '')}"
    return CACHE_DIR / sub / f"{model}_{span}_{h}.json".replace(":", "-")


def om_get(url: str, lat: float = LAT, lon: float = LON, cache: bool = True, retries: int = 6, **params) -> dict:
    """GET с retry (429/5xx/сетевые ошибки, backoff 2**i) и JSON-кешем. timezone/wind_speed_unit форсируются."""
    params = {"latitude": lat, "longitude": lon, **params, **COMMON}
    path = cache_path(url, params)
    if cache and path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if CACHE_ONLY:
        raise CacheMiss(f"OPEN_METEO_CACHE_ONLY=1: нет в кеше {path.relative_to(REPO)} ({url} {params})")
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=180)
        except requests.RequestException as e:  # DNS/timeout/reset
            last = repr(e)
            time.sleep(2 ** i)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(2 ** i)
            continue
        if r.status_code == 400:
            try:
                reason = r.json().get("reason", r.text)
            except ValueError:
                reason = r.text
            raise ValueError(f"Open-Meteo 400: {reason} ({url} {params})")
        r.raise_for_status()
        js = r.json()
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(js, f, ensure_ascii=False)
        return js
    raise RuntimeError(f"Open-Meteo: {retries} попыток исчерпано ({last}) для {url}")


def hourly_df(js: dict) -> pd.DataFrame:
    """hourly-блок ответа -> DataFrame, индекс ts (tz-aware UTC). Падает, если ветер пришёл в km/h (дефолт API).
    Единица 'undefined' у полностью null-колонок (например wind_speed_80m у ecmwf_ifs025) допустима."""
    units = js.get("hourly_units", {})
    bad = {k: u for k, u in units.items() if k.startswith(("wind_speed", "wind_gusts")) and u == "km/h"}
    if bad:
        raise ValueError(f"ветер в km/h: {bad} — забыт wind_speed_unit=ms")
    df = pd.DataFrame(js["hourly"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")
    df.index.name = "ts"
    df.attrs.update(grid=(js.get("latitude"), js.get("longitude")), elevation=js.get("elevation"), units=units)
    return df


def hourly_df_from_json(path: str | Path) -> pd.DataFrame:
    """Сохранённый ответ API (например data/nwp_cache/previous_runs_feb2026/<model>.json) -> DataFrame."""
    with open(path, encoding="utf-8") as f:
        return hourly_df(json.load(f))


def _guard_test_window(fn: str, start: str, end: str, allow: bool) -> None:
    if not allow and start <= TEST_WINDOW[1] and end >= TEST_WINDOW[0]:
        raise ValueError(
            f"{fn}: диапазон {start}..{end} пересекает тестовое окно {TEST_WINDOW[0]}..{TEST_WINDOW[1]}; "
            "это не as-issued источник (leak). Для eval-целей передайте allow_test_window=True осознанно."
        )


# ---------------------------------------------------------------- 1. Previous Runs (as-issued, фиксированный lead)
def previous_runs(model: str, start: str, end: str, variables=("wind_speed_100m",), days=(1, 2),
                  lat: float = LAT, lon: float = LON) -> pd.DataFrame:
    """<var>_previous_dayN на валидный час h дня D == ран, инициализированный на D-N в том же 6-часовом блоке
    (00/06/12/18Z), т.е. lead 24N..24N+5 ч. Проверено 1:1 против Single Runs для ecmwf_ifs (Feb 2026, 0 расхождений).
    Архив: см. PREV_MODELS. Никогда не использовать models=best_match."""
    hv = ",".join(f"{v}_previous_day{n}" for v in variables for n in days)
    js = om_get(URL_PREVIOUS_RUNS, lat=lat, lon=lon, hourly=hv, start_date=start, end_date=end, models=model)
    return hourly_df(js)


def previous_runs_chunked(model: str, start: str, end: str, variables=("wind_speed_100m",), days=(1, 2),
                          chunk_days: int = 14, pause_s: float = 0.2) -> pd.DataFrame:
    """То же, но диапазон режется на куски по chunk_days (weighted-вызовы free tier). Для дампа 2024-03 -> 2026-02."""
    parts = []
    s = pd.Timestamp(start)
    stop = pd.Timestamp(end)
    while s <= stop:
        e = min(s + pd.Timedelta(days=chunk_days - 1), stop)
        parts.append(previous_runs(model, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"), variables, days))
        s = e + pd.Timedelta(days=1)
        if s <= stop and not CACHE_ONLY:
            time.sleep(pause_s)
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------- 2. Single Runs (as-issued, полный горизонт рана)
def single_run(run_iso_utc: str, model: str = "ecmwf_ifs", forecast_days: int = 4, hourly: str = WX_VARS,
               lat: float = LAT, lon: float = LON) -> pd.DataFrame:
    """Полный почасовой горизонт одного рана; t0 == run. Колонки + lead_h, run_init_utc.
    ecmwf_ifs 9 km: раны 00/06/12/18Z с 2024-03-14 (00/12Z до 240 ч, 06/18Z до 144 ч).
    Остальные модели в Single Runs только с 2026-04-02 -> для Feb 2026 HTTP 400."""
    js = om_get(URL_SINGLE_RUNS, lat=lat, lon=lon, run=run_iso_utc, models=model, hourly=hourly,
                forecast_days=forecast_days)
    df = hourly_df(js)
    df["lead_h"] = range(len(df))
    df["run_init_utc"] = run_iso_utc
    return df


# ---------------------------------------------------------------- 3. Archive (реанализ) — только train/eval
def archive_era5(start: str, end: str, hourly: str = ERA5_VARS, model: str = "era5",
                 allow_test_window: bool = False, lat: float = LAT, lon: float = LON) -> pd.DataFrame:
    """ERA5 0.25° (грид 43.75/78.5), задержка ~5 дней. models=era5 ОБЯЗАТЕЛЕН: без models (best_match) этот
    эндпоинт здесь отдаёт анализ/короткий прогноз IFS 9 km, побайтно равный Historical Forecast ecmwf_ifs.
    era5_land не имеет wind_speed_100m. Реанализ — не прогноз: в тестовом окне это утечка (см. TEST_WINDOW)."""
    _guard_test_window("archive_era5", start, end, allow_test_window)
    js = om_get(URL_ARCHIVE, lat=lat, lon=lon, hourly=hourly, start_date=start, end_date=end, models=model)
    return hourly_df(js)


# ---------------------------------------------------------------- 4. Historical Forecast — НЕ as-issued, только train
def historical_forecast(start: str, end: str, model: str = "ecmwf_ifs", hourly: str = WX_VARS,
                        allow_test_window: bool = False, lat: float = LAT, lon: float = LON) -> pd.DataFrame:
    """NOT as-issued: склейка первых часов каждого рана (часы 00-05 из 00Z, 06-11 из 06Z, ...), lead 0-5 ч,
    т.е. почти анализ. Проверено: Feb-1 06-11 == ран 2026-02-01T06 часы 0-5. ТОЛЬКО для обучения / pre-train.
    Для бэктеста Feb 2026 запрещён. Старт: ecmwf_ifs 2017-01, gfs_global 2021-03, icon_global 2022-11."""
    _guard_test_window("historical_forecast", start, end, allow_test_window)
    js = om_get(URL_HISTORICAL_FORECAST, lat=lat, lon=lon, hourly=hourly, start_date=start, end_date=end,
                models=model)
    return hourly_df(js)


if __name__ == "__main__":
    print(f"repo={REPO}\ncache_dir={CACHE_DIR.relative_to(REPO)}  OPEN_METEO_CACHE_ONLY={CACHE_ONLY}")
    print(f"turbines={TURBINES}  common={COMMON}")
    sample = CACHE_DIR / "previous_runs_feb2026" / "ecmwf_ifs.json"
    if sample.exists():
        d = hourly_df_from_json(sample)
        print(f"{sample.relative_to(REPO)}: shape={d.shape} grid={d.attrs['grid']} {d.index.min()} .. {d.index.max()}")
        print(d[["wind_speed_100m_previous_day1", "wind_speed_100m_previous_day2"]].head(3).to_string())
    else:
        print("нет", sample.relative_to(REPO))
    if "--live" in sys.argv:  # один сетевой вызов для проверки эндпоинта
        pr = previous_runs("icon_global", "2026-02-01", "2026-02-01")
        print("live previous_runs icon_global 2026-02-01:", pr.shape, pr.attrs["grid"])
        print(pr.head(3).to_string())

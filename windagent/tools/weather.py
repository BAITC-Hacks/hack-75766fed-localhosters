"""Open-Meteo client with permanent HTTP and portable JSON caches.

UTC model initialisation is not the publication time; consumers must apply an
availability policy before selecting forecasts for an as-of backtest.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import pandas as pd
import requests
import requests_cache
import yaml

ROOT = Path(__file__).resolve().parents[2]
SINGLE_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
PREVIOUS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLES = (
    "wind_speed_100m",
    "wind_speed_80m",
    "wind_speed_10m",
    "wind_direction_100m",
    "wind_gusts_10m",
    "temperature_2m",
    "surface_pressure",
)
T1 = (43.645150, 78.535604)
T2 = (43.643198, 78.538828)
PREVIOUS_MODELS = {
    "icon_global": "2024-02-16",
    "gfs_global": "2024-02-16",
    "ecmwf_ifs025": "2024-03-06",
    "ecmwf_aifs025_single": "2025-02-18",
    "ecmwf_ifs": "2025-10-01",
}
PREVIOUS_VARIABLES = {
    "ws100": "wind_speed_100m",
    "ws80": "wind_speed_80m",
    "ws10": "wind_speed_10m",
    "dir100": "wind_direction_100m",
    "T2m": "temperature_2m",
    "sp": "surface_pressure",
    "gusts": "wind_gusts_10m",
}
DEFAULT_PREVIOUS_VARS = ("ws100", "ws80", "ws10", "dir100", "T2m", "sp")
COARSE_ECMWF = {"ecmwf_ifs025", "ecmwf_aifs025_single"}


def site_coordinates(site_id: str) -> tuple[float, float]:
    """Read the approved site registry, not an arbitrary caller-supplied path."""
    if site_id not in {"T1", "T2"}:
        raise ValueError(f"Unknown site_id: {site_id}")
    path = ROOT / "config" / "sites" / f"{site_id}.yaml"
    site = yaml.safe_load(path.read_text(encoding="utf-8"))
    latitude, longitude = float(site["latitude"]), float(site["longitude"])
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError(f"Invalid coordinates for {site_id}")
    return latitude, longitude


def previous_variable_names(model: str, variables: tuple[str, ...]) -> tuple[str, ...]:
    if model not in PREVIOUS_MODELS:
        raise ValueError(f"Unsupported Previous Runs model: {model}")
    if not variables:
        raise ValueError("At least one Previous Runs variable is required")
    invalid = set(variables) - PREVIOUS_VARIABLES.keys()
    if invalid:
        raise ValueError(f"Unsupported Previous Runs variables: {sorted(invalid)}")
    if "gusts" in variables and model not in {"icon_global", "gfs_global"}:
        raise ValueError(f"wind_gusts_10m is unavailable for {model}")
    if "ws80" in variables and model in COARSE_ECMWF:
        raise ValueError(f"wind_speed_80m is unavailable for {model}")
    return tuple(PREVIOUS_VARIABLES[name] for name in dict.fromkeys(variables))


class CacheMissError(RuntimeError):
    """A requested response is absent from both caches in offline mode."""


def run_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if dt.hour not in (0, 6, 12, 18) or dt.minute or dt.second or dt.microsecond:
        raise ValueError("run must be a UTC 00/06/12/18 cycle, without seconds")
    return dt


def normalized_params(params: dict[str, Any]) -> dict[str, Any]:
    return {**params, "timezone": "UTC", "wind_speed_unit": "ms"}


def request_key(url: str, params: dict[str, Any]) -> str:
    request = requests.Request(
        "GET", url, params=sorted(normalized_params(params).items())
    )
    return hashlib.sha256(request.prepare().url.encode()).hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # One writer per dump; replacement prevents partial cache entries on failure.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


class WeatherClient:
    def __init__(
        self,
        root: Path = ROOT,
        *,
        cache_only: bool | None = None,
        max_attempts: int = 4,
        request_budget: int = 190,
    ):
        if max_attempts < 1 or request_budget < 1:
            raise ValueError("max_attempts and request_budget must be positive")
        self.root = Path(root)
        self.cache_only = (
            os.getenv("OPEN_METEO_CACHE_ONLY") == "1"
            if cache_only is None
            else cache_only
        )
        self.max_attempts = max_attempts
        self.request_budget = request_budget
        self.network_attempts = 0
        self.records: dict[str, dict[str, Any]] = {}
        self.session = requests_cache.CachedSession(
            str(self.root / ".om_cache"),
            expire_after=-1,
        )

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def om_get(
        self,
        url: str,
        params: dict[str, Any],
        *,
        artifact: Path | None = None,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        if url not in (SINGLE_URL, PREVIOUS_URL):
            raise ValueError("Only the configured Open-Meteo endpoints are supported")
        if site_id is not None:
            latitude, longitude = site_coordinates(site_id)
            params = {**params, "latitude": latitude, "longitude": longitude}
        params = normalized_params(params)
        key = request_key(url, params)
        artifact = artifact or Path("data/nwp_cache/requests") / f"{key}.json"
        path = self.root / artifact
        metadata_path = path.with_suffix(".meta.json")
        if path.exists() and metadata_path.exists():
            raw = path.read_bytes()
            meta = json.loads(metadata_path.read_text())
            if meta["key"] == key:
                if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                    raise ValueError(f"Cache checksum mismatch: {artifact}")
                self.records[key] = meta
                return json.loads(raw)

        response = self.session.get(url, params=params, only_if_cached=True, timeout=30)
        if response.status_code == 504:
            if self.cache_only:
                raise CacheMissError(
                    f"Open-Meteo cache miss: key={key}, artifact={artifact}"
                )
            for attempt in range(self.max_attempts):
                if self.network_attempts >= self.request_budget:
                    raise RuntimeError("Open-Meteo request budget exhausted")
                self.network_attempts += 1
                response = self.session.get(url, params=params, timeout=(10, 60))
                if (
                    response.status_code != 429
                    and not 500 <= response.status_code < 600
                ):
                    break
                if attempt + 1 < self.max_attempts:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.isdigit() else 2**attempt
                    time.sleep(min(delay, 60))
        response.raise_for_status()
        data = response.json()
        if data.get("error") or "hourly" not in data:
            self.session.cache.delete(self.session.cache.create_key(response.request))
            raise ValueError(f"Invalid Open-Meteo response for key={key}: {data}")
        raw = response.content
        created = getattr(response, "created_at", None)
        meta = {
            "key": key,
            "url": url,
            "params": params,
            "fetched_at": (created or datetime.now(UTC)).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "grid": {k: data.get(k) for k in ("latitude", "longitude", "elevation")},
            "path": str(artifact),
        }
        atomic_write(path, raw)
        atomic_write(metadata_path, (json.dumps(meta, indent=2) + "\n").encode())
        self.records[key] = meta
        return data

    def single_run(
        self,
        run_iso: str,
        model: str = "ecmwf_ifs",
        forecast_days: int = 4,
        *,
        site_id: str = "T1",
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, Any]:
        if model != "ecmwf_ifs":
            raise ValueError("This archive currently supports only ecmwf_ifs")
        if not 1 <= forecast_days <= 10:
            raise ValueError("forecast_days must be in 1..10")
        site_latitude, site_longitude = site_coordinates(site_id)
        latitude = site_latitude if latitude is None else latitude
        longitude = site_longitude if longitude is None else longitude
        run = run_datetime(run_iso).strftime("%Y-%m-%dT%H:%M")
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "run": run,
            "models": model,
            "hourly": ",".join(VARIABLES),
            "forecast_days": forecast_days,
        }
        artifact = None
        if (latitude, longitude) == T1 and forecast_days == 4:
            artifact = Path(
                f"data/nwp_cache/single_runs/{model}/{run.replace(':', '')}Z.json"
            )
        return self.om_get(SINGLE_URL, params, artifact=artifact)

    def previous_runs(
        self,
        model: str,
        start: str,
        end: str,
        variables: tuple[str, ...] = DEFAULT_PREVIOUS_VARS,
        *,
        site_id: str = "T1",
    ) -> pd.DataFrame:
        """Fetch day1/day2 features in inclusive, at most 14-day UTC chunks."""
        names = previous_variable_names(model, variables)
        latitude, longitude = site_coordinates(site_id)
        first, last = pd.Timestamp(start), pd.Timestamp(end)
        if first.tzinfo is not None or last.tzinfo is not None:
            raise ValueError("start and end must be UTC calendar dates")
        if first != first.normalize() or last != last.normalize() or first > last:
            raise ValueError("Provide an ordered range of UTC calendar dates")
        if first < pd.Timestamp(PREVIOUS_MODELS[model]):
            raise ValueError(f"{model} archive starts {PREVIOUS_MODELS[model]}")
        hourly = ",".join(
            f"{name}_previous_day{day}" for name in names for day in (1, 2)
        )
        parts = []
        cursor = first
        while cursor <= last:
            stop = min(cursor + pd.Timedelta(days=13), last)
            start_date, end_date = cursor.date().isoformat(), stop.date().isoformat()
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "models": model,
                "hourly": hourly,
                "start_date": start_date,
                "end_date": end_date,
            }
            artifact = Path(
                f"data/nwp_cache/previous_runs/{site_id}/{model}/"
                f"{start_date}_{end_date}.json"
            )
            data = self.om_get(PREVIOUS_URL, params, artifact=artifact)
            if data.get("utc_offset_seconds") != 0:
                raise ValueError(f"Previous Runs response is not UTC: {artifact}")
            expected = pd.date_range(
                start_date, end_date + " 23:00", freq="h", tz="UTC"
            )
            hourly_data = data["hourly"]
            frame = pd.DataFrame(hourly_data)
            if len(frame) != len(expected):
                raise ValueError(f"Incomplete hourly grid: {artifact}")
            frame = frame.rename(columns={"time": "valid_utc"})
            frame["valid_utc"] = pd.to_datetime(frame["valid_utc"], utc=True)
            if (
                not frame["valid_utc"]
                .reset_index(drop=True)
                .equals(pd.Series(expected))
            ):
                raise ValueError(f"Unexpected hourly timestamps: {artifact}")
            for name in names:
                for day in (1, 2):
                    column = f"{name}_previous_day{day}"
                    unit = data["hourly_units"].get(column)
                    if name.startswith("wind_speed") or name == "wind_gusts_10m":
                        if unit != "m/s":
                            raise ValueError(f"Unexpected unit {unit!r} for {column}")
                    if column not in frame:
                        raise ValueError(f"Missing column {column}: {artifact}")
            parts.append(frame)
            cursor = stop + pd.Timedelta(days=1)
        result = pd.concat(parts, ignore_index=True)
        if result["valid_utc"].duplicated().any():
            raise ValueError("Duplicate Previous Runs timestamps")
        return result

    def previous_day(self, *, site_id: str = "T1") -> dict[str, Any]:
        latitude, longitude = site_coordinates(site_id)
        return self.om_get(
            PREVIOUS_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "models": "ecmwf_ifs",
                "hourly": "wind_speed_100m_previous_day1",
                "start_date": "2026-02-01",
                "end_date": "2026-02-01",
            },
        )


def om_get(
    url: str, params: dict[str, Any], *, site_id: str | None = None
) -> dict[str, Any]:
    with WeatherClient() as client:
        return client.om_get(url, params, site_id=site_id)


def single_run(
    run_iso: str,
    model: str = "ecmwf_ifs",
    forecast_days: int = 4,
    *,
    site_id: str = "T1",
) -> dict[str, Any]:
    with WeatherClient() as client:
        return client.single_run(run_iso, model, forecast_days, site_id=site_id)


def previous_runs(
    model: str,
    start: str,
    end: str,
    variables: tuple[str, ...] = DEFAULT_PREVIOUS_VARS,
    *,
    site_id: str = "T1",
) -> pd.DataFrame:
    with WeatherClient() as client:
        return client.previous_runs(model, start, end, variables, site_id=site_id)

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

import requests
import requests_cache

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
        self, url: str, params: dict[str, Any], *, artifact: Path | None = None
    ) -> dict[str, Any]:
        if url not in (SINGLE_URL, PREVIOUS_URL):
            raise ValueError("Only the configured Open-Meteo endpoints are supported")
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
        latitude: float = T1[0],
        longitude: float = T1[1],
    ) -> dict[str, Any]:
        if model != "ecmwf_ifs":
            raise ValueError("This archive currently supports only ecmwf_ifs")
        if not 1 <= forecast_days <= 10:
            raise ValueError("forecast_days must be in 1..10")
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

    def previous_day(self) -> dict[str, Any]:
        return self.om_get(
            PREVIOUS_URL,
            {
                "latitude": T1[0],
                "longitude": T1[1],
                "models": "ecmwf_ifs",
                "hourly": "wind_speed_100m_previous_day1",
                "start_date": "2026-02-01",
                "end_date": "2026-02-01",
            },
        )


def om_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    with WeatherClient() as client:
        return client.om_get(url, params)


def single_run(
    run_iso: str, model: str = "ecmwf_ifs", forecast_days: int = 4
) -> dict[str, Any]:
    with WeatherClient() as client:
        return client.single_run(run_iso, model, forecast_days)

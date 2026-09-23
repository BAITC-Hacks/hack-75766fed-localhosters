"""Shared defaults; load .env only at CLI entry, never during import."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    horizon_hours: int = 48
    scada_tz_offset_hours: int = 6
    issue_hour_utc: int = 18
    availability_lag_hours: int = 7  # compatibility for non-ECMWF adapters
    avail_lag_by_cycle: tuple[int, int, int, int] = (8, 7, 8, 7)
    divergence_threshold_ms: float = 1.5
    reissue_on_new_run: bool = True
    point_estimate: str = "median"

    @classmethod
    def from_env(cls):
        result = cls(
            horizon_hours=int(os.getenv("HORIZON_HOURS", "48")),
            scada_tz_offset_hours=int(os.getenv("SCADA_TZ_OFFSET_HOURS", "6")),
            issue_hour_utc=int(os.getenv("ISSUE_HOUR_UTC", "18")),
            availability_lag_hours=int(os.getenv("AVAIL_LAG_HOURS", "7")),
            divergence_threshold_ms=float(os.getenv("DIVERGENCE_THRESHOLD_MS", "1.5")),
            reissue_on_new_run=os.getenv("REISSUE_ON_NEW_RUN", "1") == "1",
            point_estimate=os.getenv("POINT_ESTIMATE", "median"),
        )
        if not 1 <= result.horizon_hours <= 48:
            raise ValueError("HORIZON_HOURS must be 1..48")
        if not 0 <= result.issue_hour_utc <= 23 or result.availability_lag_hours < 0:
            raise ValueError("Invalid issue hour or availability lag")
        if result.point_estimate not in {"median", "mean", "cost"}:
            raise ValueError("POINT_ESTIMATE must be median, mean or cost")
        return result
# LOC-8: shared SCADA conventions.
SCADA_TZ = "Etc/GMT-6"
SCADA_TZ_OFFSET_HOURS = 6
HOURLY_LABEL = os.getenv("HOURLY_LABEL", "left").lower()
if HOURLY_LABEL not in {"left", "right"}:
    raise ValueError("HOURLY_LABEL must be left or right")
MIN_SAMPLES_PER_HOUR = int(os.getenv("MIN_SAMPLES_PER_HOUR", "4"))
if not 1 <= MIN_SAMPLES_PER_HOUR <= 6:
    raise ValueError("MIN_SAMPLES_PER_HOUR must be between 1 and 6")

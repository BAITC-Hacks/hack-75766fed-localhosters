"""Versioned wire contracts; UTC timestamps label interval starts (+0…+H−1)."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Timestamp must include UTC timezone")
    if value.minute or value.second or value.microsecond:
        raise ValueError("Timestamp must be on an hourly boundary")
    return value.astimezone(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WeatherHour(Contract):
    valid_time_utc: datetime
    wind_speed_100m_ms: float = Field(ge=0, le=100)
    wind_direction_100m_deg: float = Field(ge=0, le=360)
    temperature_2m_c: float = Field(ge=-100, le=70)
    # Optional since LOC-12: the v1 model needs them, v0 and the demo curve do not.
    wind_speed_80m_ms: float | None = Field(default=None, ge=0, le=100)
    wind_speed_10m_ms: float | None = Field(default=None, ge=0, le=100)
    surface_pressure_hpa: float | None = Field(default=None, ge=300, le=1100)
    _utc = field_validator("valid_time_utc")(utc)


class NwpForecast(Contract):
    schema_version: Literal["1.0"] = "1.0"
    source: str
    model: str
    data_kind: Literal["demo", "archive"]
    run_init_utc: datetime
    available_at_utc: datetime
    hourly: list[WeatherHour] = Field(min_length=1)
    _utc = field_validator("run_init_utc", "available_at_utc")(utc)

    @model_validator(mode="after")
    def chronology(self):
        if self.available_at_utc < self.run_init_utc:
            raise ValueError("NWP available before initialization")
        times = [row.valid_time_utc for row in self.hourly]
        if times != sorted(set(times)):
            raise ValueError("NWP hours must be sorted and unique")
        return self


class ScadaWindow(Contract):
    as_of_utc: datetime
    rows: list[dict] = Field(default_factory=list)
    status: Literal["missing", "available"] = "missing"
    _utc = field_validator("as_of_utc")(utc)


class DataQualityReport(Contract):
    accepted: bool
    issues: list[str] = Field(default_factory=list)
    expected_hours: int
    available_hours: int
    data_kind: Literal["demo", "archive"]


class PowerHour(Contract):
    valid_time_utc: datetime
    power_normalized: float = Field(ge=0, le=1)
    p10: float | None = Field(default=None, ge=0, le=1)
    p90: float | None = Field(default=None, ge=0, le=1)
    _utc = field_validator("valid_time_utc")(utc)

    @model_validator(mode="after")
    def interval(self):
        if (self.p10 is None) != (self.p90 is None):
            raise ValueError("Provide both interval bounds or neither")
        if self.p10 is not None and not self.p10 <= self.power_normalized <= self.p90:
            raise ValueError("Crossed prediction quantiles")
        return self


class PowerForecast(Contract):
    schema_version: Literal["1.0"] = "1.0"
    model_version: str
    prediction_kind: Literal["demo", "model"]
    turbine_id: Literal["turbine_1", "turbine_2"]
    forecast_origin_utc: datetime
    horizon_hours: int = Field(ge=1, le=48)
    target: Literal["hourly_mean_normalized_active_power"] = "hourly_mean_normalized_active_power"
    interval_label: Literal["start"] = "start"
    hourly: list[PowerHour]
    _utc = field_validator("forecast_origin_utc")(utc)

    @model_validator(mode="after")
    def horizon(self):
        expected = [self.forecast_origin_utc + timedelta(hours=i) for i in range(self.horizon_hours)]
        if [row.valid_time_utc for row in self.hourly] != expected:
            raise ValueError("INCOMPLETE_HORIZON: require consecutive +0…+H−1 interval starts")
        return self


class IssueDecision(Contract):
    publish: bool
    reason: str
    used_runs: list[str]
    corrections: list[str] = Field(default_factory=list)
    reissue_recommended: bool = False
    summary_ru: str

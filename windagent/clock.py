"""As-of часы: какой ран ECMWF IFS был реально доступен на момент выпуска прогноза.

Инициализация рана != момент публикации. ECMWF open data выкладывает раны в конце
диссеминации: 00Z ≈07:34, 06Z ≈12:27, 12Z ≈19:34, 18Z ≈00:27 UTC (Last-Modified всех
ранов Feb 2026 в бакете ecmwf-forecasts). Отсюда задержка по циклам: +8 ч для 00Z/12Z,
+7 ч для 06Z/18Z. Константа +7 ч пропускала бы 12Z в 19:00 UTC — утечка.

Конвенция выпуска (dayahead): issue_time = 18:00 UTC дня D−1 = 00:00 по часам SCADA дня D
(SCADA идёт в фиксированном UTC+6). Горизонт — 48 часов от issue_time: сутки D и D+1.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
SCADA_TZ_OFFSET_H = 6
SCADA_TZ = timezone(timedelta(hours=SCADA_TZ_OFFSET_H))
ISSUE_HOUR_UTC = 18
HORIZON_H = 48
AVAIL_LAG_H = {0: 8, 6: 7, 12: 8, 18: 7}  # цикл рана (UTC) -> часов до публичной доступности


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def available_at(run_init: datetime) -> datetime:
    """Момент, с которого ран можно использовать (публикация open data + запас)."""
    run_init = _utc(run_init)
    if run_init.hour not in AVAIL_LAG_H or run_init.minute or run_init.second:
        raise ValueError(f"run_init must be a 00/06/12/18Z cycle: {run_init.isoformat()}")
    return run_init + timedelta(hours=AVAIL_LAG_H[run_init.hour])


def is_available(run_init: datetime, at: datetime) -> bool:
    return available_at(run_init) <= _utc(at)


def latest_available_run(at: datetime, run_inits) -> datetime | None:
    """Самый свежий ран из run_inits, доступный на момент at (None, если такого нет)."""
    at = _utc(at)
    ok = [_utc(r) for r in run_inits if is_available(r, at)]
    return max(ok) if ok else None


def issue_time_for_day(day: date) -> datetime:
    """00:00 по SCADA дня day == 18:00 UTC предыдущего дня."""
    return datetime(day.year, day.month, day.day, ISSUE_HOUR_UTC, tzinfo=UTC) - timedelta(days=1)


def dayahead_issues(first_target_day: date, last_target_day: date) -> list[datetime]:
    """Выпуски для каждого целевого дня в диапазоне (включительно)."""
    out, day = [], first_target_day
    while day <= last_target_day:
        out.append(issue_time_for_day(day))
        day += timedelta(days=1)
    return out


def targets(issue_time: datetime, horizon_h: int = HORIZON_H) -> list[datetime]:
    issue_time = _utc(issue_time)
    return [issue_time + timedelta(hours=h) for h in range(horizon_h)]


def lead_h(run_init: datetime, target: datetime) -> int:
    delta = (_utc(target) - _utc(run_init)).total_seconds() / 3600
    if delta != int(delta):
        raise ValueError("target must be on the hourly grid")
    return int(delta)


def to_scada(dt: datetime) -> datetime:
    return _utc(dt).astimezone(SCADA_TZ)


def iso_utc(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_scada(dt: datetime) -> str:
    return to_scada(dt).strftime("%Y-%m-%dT%H:%M:%S+06:00")

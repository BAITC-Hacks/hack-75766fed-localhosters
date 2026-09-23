"""Offline issue runner. No training, network fetching or implicit demo fallback."""
import csv
import importlib
import json
import math
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from windagent.config import Settings
from windagent.clock import assert_as_of, available_at
from windagent.schemas import DataQualityReport, NwpForecast, PowerForecast, ScadaWindow, utc
from windagent.agent.scripted import ScriptedPlanner
from windagent.agent.trace import Trace


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def read_previous(root, at, demo):
    candidates = []
    for path in root.glob("*/inputs.json"):
        status_path = path.parent / "status.json"
        if not status_path.exists() or json.loads(status_path.read_text()).get("status") != "published":
            continue
        data = json.loads(path.read_text())
        origin = datetime.fromisoformat(data["issue_time_utc"].replace("Z", "+00:00"))
        if origin < at and data["data_kind"] == ("demo" if demo else "archive"):
            candidates.append((origin, path.parent.name, path.parent, data))
    if not candidates:
        return None
    _, _, path, inputs = max(candidates)
    return {"path": str(path), "inputs": inputs, "memory": json.loads((path / "memory.json").read_text())}


def read_archive_run(path, run):
    """LOC-14 stores the original Open-Meteo response in one file per run."""
    raw = json.loads(path.read_text())
    if raw.get("hourly_units", {}).get("wind_speed_100m") != "m/s":
        raise ValueError(f"INVALID_UNITS: {path}")
    hourly = raw["hourly"]
    return NwpForecast.model_validate({
        "source": "Open-Meteo Single Runs", "model": "ecmwf_ifs", "data_kind": "archive",
        "run_init_utc": run, "available_at_utc": available_at(run),
        "hourly": [{
            "valid_time_utc": datetime.fromisoformat(time).replace(tzinfo=timezone.utc),
            "wind_speed_100m_ms": hourly["wind_speed_100m"][i],
            "wind_direction_100m_deg": hourly["wind_direction_100m"][i],
            "temperature_2m_c": hourly["temperature_2m"][i],
            "wind_speed_80m_ms": hourly.get("wind_speed_80m", [None] * len(hourly["time"]))[i],
            "wind_speed_10m_ms": hourly.get("wind_speed_10m", [None] * len(hourly["time"]))[i],
            "surface_pressure_hpa": hourly.get("surface_pressure", [None] * len(hourly["time"]))[i],
        } for i, time in enumerate(hourly["time"]) if hourly["wind_speed_100m"][i] is not None],
    })


def fetch_nwp_forecast(cache, at, settings, demo):
    if not demo:
        # The cache holds hundreds of runs (LOC-18 training dump): pick by file name, parse newest first,
        # and skip a run with missing values instead of failing the whole issue.
        runs = []
        for path in cache.glob("????-??-??T????Z.json"):
            run = datetime.strptime(path.stem, "%Y-%m-%dT%H%MZ").replace(tzinfo=timezone.utc)
            if available_at(run) <= at:
                runs.append((run, path))
        for run, path in sorted(runs, reverse=True):
            try:
                forecast = read_archive_run(path, run)
            except ValidationError:
                continue
            assert_as_of(at, forecast.run_init_utc, [row.valid_time_utc for row in forecast.hourly if row.valid_time_utc >= at])
            return forecast, path
        raise ValueError(f"WEATHER_NOT_AVAILABLE: no eligible archive run in {cache}")
    candidates = []
    for path in sorted(cache.glob("*.json")):
        if path.name == "manifest.json":
            continue
        forecast = NwpForecast.model_validate_json(path.read_text())
        if forecast.data_kind != "demo":
            continue
        available = max(forecast.available_at_utc, available_at(forecast.run_init_utc))
        if available <= at:
            candidates.append((forecast.run_init_utc, path.name, forecast, path))
    if not candidates:
        raise ValueError(f"WEATHER_NOT_AVAILABLE: no eligible demo run in {cache}")
    _, _, forecast, path = max(candidates, key=lambda item: item[:2])
    assert_as_of(at, forecast.run_init_utc, [row.valid_time_utc for row in forecast.hourly if row.valid_time_utc >= at])
    return forecast, path


def check_data_quality(forecast, at, settings):
    expected = [at + timedelta(hours=i) for i in range(settings.horizon_hours)]
    available = {row.valid_time_utc for row in forecast.hourly}
    missing = [iso(t) for t in expected if t not in available]
    return DataQualityReport(
        accepted=not missing, issues=[f"Missing hour: {t}" for t in missing],
        expected_hours=len(expected), available_hours=len(set(expected) & available), data_kind=forecast.data_kind,
    )


def predict_power(request, demo, model_adapter=None):
    if demo:
        # Unfitted illustrative curve. No artificial confidence bounds or accuracy.
        return PowerForecast.model_validate({
            "model_version": "demo-curve-v0", "prediction_kind": "demo",
            "turbine_id": request["turbine_id"], "forecast_origin_utc": request["forecast_origin_utc"],
            "horizon_hours": request["horizon_hours"],
            "hourly": [{"valid_time_utc": row["valid_time_utc"],
                        "power_normalized": round(1 / (1 + math.exp(-0.705 * (row["wind_speed_100m_ms"] - 7.89))), 6)}
                       for row in request["hourly"]],
        })
    if not model_adapter:
        raise ValueError("MODEL_NOT_FOUND: pass --model-adapter module:function; use --demo only for an explicit demo")
    module, function = model_adapter.split(":", 1)
    result = PowerForecast.model_validate(getattr(importlib.import_module(module), function)(request))
    if result.prediction_kind != "model":
        raise ValueError("MODEL_NOT_FOUND: production adapter returned demo")
    if (result.turbine_id != request["turbine_id"] or
            iso(result.forecast_origin_utc) != request["forecast_origin_utc"] or
            result.horizon_hours != request["horizon_hours"]):
        raise ValueError("MODEL_CONTRACT_MISMATCH: turbine/origin/horizon differ from request")
    return result


def compare_with_previous(previous, forecasts, weather):
    if previous is None:
        return {"previous": None, "overlap_hours": 0, "mean_abs_delta": None, "divergence_ms": None, "new_run": True}
    root = Path(previous["path"])
    with (root / "forecast.csv").open() as file:
        old = {(row["turbine"], row["target_time_utc"]): float(row["point"]) for row in csv.DictReader(file)}
    deltas = [abs(row.power_normalized - old[key]) for f in forecasts for row in f.hourly
              if (key := (f.turbine_id, iso(row.valid_time_utc))) in old]
    old_weather = {row["valid_time_utc"]: row["wind_speed_100m_ms"] for row in previous["inputs"]["hourly"]}
    wind_deltas = [row.wind_speed_100m_ms - old_weather[iso(row.valid_time_utc)] for row in weather
                   if iso(row.valid_time_utc) in old_weather]
    return {"previous": root.name, "overlap_hours": len(deltas),
            "mean_abs_delta": sum(deltas) / len(deltas) if deltas else None,
            "divergence_ms": abs(sum(wind_deltas) / len(wind_deltas)) if wind_deltas else None,
            "new_run": previous["inputs"]["nwp_run_init_utc"] != previous.get("current_run")}


def save_forecast(path, forecasts, inputs, settings):
    fields = ["issue_time_utc", "issue_time_scada", "target_time_scada", "target_time_utc", "turbine", "lead_h",
              "nwp_run_init_utc", "nwp_lead_h", "point", "p10", "p50", "p90", "prediction_kind", "model_version", "interval_label"]
    zone = timezone(timedelta(hours=settings.scada_tz_offset_hours))
    origin = datetime.fromisoformat(inputs["issue_time_utc"].replace("Z", "+00:00"))
    run = datetime.fromisoformat(inputs["nwp_run_init_utc"].replace("Z", "+00:00"))
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for forecast in forecasts:
            for row in forecast.hourly:
                writer.writerow({
                    "issue_time_utc": iso(origin), "issue_time_scada": origin.astimezone(zone).isoformat(),
                    "target_time_utc": iso(row.valid_time_utc), "target_time_scada": row.valid_time_utc.astimezone(zone).isoformat(),
                    "turbine": forecast.turbine_id, "lead_h": int((row.valid_time_utc - origin).total_seconds() / 3600),
                    "nwp_run_init_utc": iso(run), "nwp_lead_h": int((row.valid_time_utc - run).total_seconds() / 3600),
                    "point": row.power_normalized, "p10": row.p10,
                    "p50": row.power_normalized if settings.point_estimate == "median" and forecast.prediction_kind == "model" else None,
                    "p90": row.p90, "prediction_kind": forecast.prediction_kind,
                    "model_version": forecast.model_version, "interval_label": "start",
                })
    return {"rows": sum(len(f.hourly) for f in forecasts), "file": path.name}


def run_issue(at, cache, output, demo=False, planner=None, settings=None, model_adapter=None):
    at = utc(at)
    settings = settings or Settings.from_env()
    planner = planner or ScriptedPlanner()
    output.mkdir(parents=True, exist_ok=True)
    directory = output / (at.strftime("%Y-%m-%dT%H-%MZ") + "-" + uuid4().hex[:8])
    directory.mkdir()
    trace = Trace()
    try:
        previous = trace.call("read_memory", {"as_of": iso(at)}, lambda: read_previous(output, at, demo),
                              lambda value: {"previous": Path(value["path"]).name if value else None})
        trace.call("get_clock", {}, lambda: {"issue_time_utc": iso(at), "availability_lag_by_cycle": settings.avail_lag_by_cycle})
        nwp, cache_path = trace.call("fetch_nwp_forecast", {"cache": str(cache)},
                                   lambda: fetch_nwp_forecast(cache, at, settings, demo),
                                   lambda value: {"nwp_run_init_utc": iso(value[0].run_init_utc), "data_kind": value[0].data_kind})
        scada = trace.call("fetch_scada_history", {"before": iso(at)}, lambda: ScadaWindow(as_of_utc=at),
                           lambda value: value.model_dump(mode="json"))
        quality = trace.call("check_data_quality", {}, lambda: check_data_quality(nwp, at, settings),
                             lambda value: value.model_dump())
        write_json(directory / "dq_report.json", quality.model_dump())
        if not quality.accepted:
            raise ValueError("INCOMPLETE_HORIZON: " + "; ".join(quality.issues))
        weather = trace.call("prepare_features", {"horizon_hours": settings.horizon_hours},
                             lambda: [row for row in nwp.hourly if at <= row.valid_time_utc < at + timedelta(hours=settings.horizon_hours)],
                             lambda value: {"hours": len(value), "feature_engineering": "owned by ML adapter"})
        inputs = {
            "schema_version": "1.0", "issue_time_utc": iso(at), "nwp_run_init_utc": iso(nwp.run_init_utc),
            "nwp_available_at_utc": iso(nwp.available_at_utc), "data_kind": nwp.data_kind,
            "weather_source": nwp.source, "weather_model": nwp.model,
            "cache_sha256": sha256(cache_path.read_bytes()).hexdigest(), "planner": planner.mode,
            "interval_label": "start", "point_estimate": settings.point_estimate,
            "scada_status": scada.status, "hourly": [row.model_dump(mode="json") for row in weather],
        }
        write_json(directory / "inputs.json", inputs)
        def predict_both():
            return [predict_power({
                "schema_version": "1.0", "turbine_id": turbine, "forecast_origin_utc": iso(at),
                "horizon_hours": settings.horizon_hours, "weather_source": nwp.source, "weather_model": nwp.model,
                "weather_run_time_utc": iso(nwp.run_init_utc), "weather_available_at_utc": iso(nwp.available_at_utc),
                "interval_label": "start", "point_estimate": settings.point_estimate, "hourly": inputs["hourly"],
            }, demo, model_adapter) for turbine in ["turbine_1", "turbine_2"]]
        forecasts = trace.call("predict_power", {"adapter": model_adapter or "demo-curve-v0"}, predict_both,
                               lambda value: {"turbines": len(value), "model_version": value[0].model_version})
        if previous:
            previous["current_run"] = iso(nwp.run_init_utc)
        comparison = trace.call("compare_with_previous", {}, lambda: compare_with_previous(previous, forecasts, weather))
        context = {**comparison, "quality": quality.model_dump(), "nwp_run_init_utc": iso(nwp.run_init_utc),
                   "threshold_ms": settings.divergence_threshold_ms, "reissue_on_new_run": settings.reissue_on_new_run}
        decision = planner.decide(context)
        if decision.used_runs != [iso(nwp.run_init_utc)] or decision.corrections:
            raise ValueError("UNSUPPORTED_DECISION: invented source or unapplied correction")
        trace.rows[-1].update(decision=decision.reason, rationale=decision.summary_ru, tokens=getattr(planner, "usage", {"input": 0, "output": 0}))
        write_json(directory / "decision.json", decision.model_dump())
        write_json(directory / "comparison.json", comparison)
        trace.call("save_forecast", {"publish": decision.publish},
                   lambda: save_forecast(directory / "forecast.csv", forecasts, inputs, settings)
                   if decision.publish else {"skipped": decision.reason})
        def report():
            (directory / "report.md").write_text(
                f"# Выпуск {iso(at)}\n\nРежим данных: **{nwp.data_kind}**. Планировщик: {planner.mode}.\n\n"
                f"NWP: {iso(nwp.run_init_utc)}. Решение: {decision.reason}.\n\n{decision.summary_ru}\n\n"
                f"Опубликован: {decision.publish}. Пересчёт: {decision.reissue_recommended}.\n\n"
                f"Сравнение: `{json.dumps(comparison, ensure_ascii=False)}`\n\n"
                "SCADA-адаптер ещё не подключён. MAE, drift и фактическая мощность не рассчитаны.\n"
            )
            return {"file": "report.md"}
        trace.call("write_report", {}, report)
        def memory():
            write_json(directory / "memory.json", {"issue_time_utc": iso(at), "nwp_run_init_utc": iso(nwp.run_init_utc),
                                                   "published": decision.publish, "note": decision.summary_ru})
            return {"file": "memory.json"}
        trace.call("write_memory", {}, memory)
        write_json(directory / "status.json", {"status": "published" if decision.publish else "skipped"})
        return directory
    except Exception as error:
        write_json(directory / "status.json", {"status": "failed", "error": str(error)})
        raise
    finally:
        trace.write(directory / "trace.jsonl")

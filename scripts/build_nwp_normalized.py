"""Parquet с ранами (LOC-14) -> нормализованный кеш для runtime агента: data/nwp_cache/normalized/<run>.json.

Формат — `NwpForecast` из windagent/schemas.py (ветка agent-foundation): один файл на ран,
`available_at_utc` проставлен по as-of конвенции (windagent.clock, per-cycle задержка публикации),
`data_kind="archive"`. Runtime агента выбирает самый свежий ран с `available_at_utc <= issue_time`.

    PYTHONPATH=. .venv/bin/python scripts/build_nwp_normalized.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from windagent import clock

ROOT = Path(__file__).resolve().parents[1]
PARQUETS = [
    ROOT / "data/nwp/single_runs_ecmwf_ifs_feb2026.parquet",
    ROOT / "data/nwp/single_runs_ecmwf_ifs_jan2026.parquet",
]
OUT_DIR = ROOT / "data/nwp_cache/normalized"


def build(out_dir: Path = OUT_DIR, parquets=PARQUETS) -> int:
    frames = [pd.read_parquet(p) for p in parquets if p.exists()]
    if not frames:
        raise FileNotFoundError("no Single Runs parquet found")
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["run_init_utc", "valid_utc"])
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for run_init, g in df.groupby("run_init_utc"):
        run_init = run_init.to_pydatetime()
        g = g.sort_values("valid_utc")
        doc = {
            "schema_version": "1.0",
            "source": "open-meteo single-runs-api (as-issued archive)",
            "model": "ecmwf_ifs",
            "data_kind": "archive",
            "run_init_utc": clock.iso_utc(run_init),
            "available_at_utc": clock.iso_utc(clock.available_at(run_init)),
            "hourly": [
                {
                    "valid_time_utc": clock.iso_utc(r.valid_utc.to_pydatetime()),
                    "wind_speed_100m_ms": round(float(r.wind_speed_100m), 3),
                    "wind_direction_100m_deg": float(r.wind_direction_100m) % 360.0,
                    "temperature_2m_c": round(float(r.temperature_2m), 2),
                }
                for r in g.itertuples()
                if pd.notna(r.wind_speed_100m)
            ],
        }
        name = f"ecmwf_ifs_{run_init.strftime('%Y-%m-%dT%H')}Z.json"
        (out_dir / name).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
        n += 1
    (out_dir / "manifest.json").write_text(json.dumps({
        "runs": n, "model": "ecmwf_ifs", "availability_rule_h": clock.AVAIL_LAG_H,
        "sources": [str(p.relative_to(ROOT)) for p in parquets if p.exists()],
    }, indent=2) + "\n")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    print(f"{args.out}: {build(args.out)} runs")


if __name__ == "__main__":
    main()

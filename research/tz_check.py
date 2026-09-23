"""Проверка таймзоны SCADA: кросс-корреляция 10-мин SCADA (часы файла) vs ERA5 (UTC) при лагах 3..9 ч.

Провенанс: eda/eda_tz2.py + verify_tz/tzverify.py + tzcheck2.py ресёрч-агента (2026-09-23), переписано
для offline-запуска из data/era5/era5_YYYY-MM.csv (истинный ERA5, models=era5, грид 43.75/78.5, UTC, m/s).
Помесячные числа 1:1 совпадают с research/results/tz_lag_10min.csv.

Гипотеза: часы файла = UTC + L. ERA5 интерполируется на 10-мин сетку, индекс сдвигается на +L, join
с SCADA по naive-меткам, corr(ws_scada, ws100_era5). Пик по L и есть смещение. Ожидание для
фиксированного UTC+6: пик ~5.8 ч (6 ч минус ~10 мин, т.к. метка SCADA — конец 10-мин интервала);
для Asia/Almaty после 2024-03-01 пик сместился бы к ~4.8 ч. Температура пикует на +6.7..7.5 ч —
тепловая инерция датчика на гондоле, для вердикта не используется.

Окна: все месяцы в data/era5 (3 до 2024-03-01, 8 после). Вердикт — по pooled-скану за период (суммы
статистик по всем месяцам периода): один месяц на грубом 0.25° ERA5 может дать пик 5.0 (2026-01), но
pooled-пик и до, и после 2024-03-01 сидит на ~6 ч. Плюс проверка непрерывности 10-мин строк вокруг
2024-02-29 22:00 -> 2024-03-01 02:00 (25 строк, без дублей => часы не переводились).

Запуск: python3 research/tz_check.py [--turbine T1|T2|both] [--fetch YYYY-MM ...]
  --fetch докачивает месяцы через archive_era5() в data/era5 (нужна сеть), иначе всё offline.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from research.scada_load import FILES, load_raw  # noqa: E402

ERA5_DIR = REPO / "data" / "era5"
SWITCH = pd.Timestamp("2024-03-01")  # переход Казахстана UTC+6 -> UTC+5 (SCADA его НЕ сделала)
LAGS_MIN = range(3 * 60, 9 * 60 + 1, 10)
PAIRS = (("ws", "wind_speed_100m"), ("temp", "temperature_2m"))
OK_RANGE = (5.5, 6.5)


def era5_month(month: str) -> pd.DataFrame:
    return pd.read_csv(ERA5_DIR / f"era5_{month}.csv", parse_dates=["time"]).set_index("time")  # naive UTC


def lag_stats(scada10: pd.Series, model_h: pd.Series) -> dict[float, np.ndarray]:
    """Для каждого лага L (часы): суммарные статистики [n, Σx, Σy, Σxy, Σx², Σy²] по inner-join
    SCADA(t_file) vs model(t_utc + L). Суммы аддитивны -> можно пулить по месяцам."""
    m10 = model_h.resample("10min").interpolate("linear")
    out = {}
    for L in LAGS_MIN:
        m = m10.copy()
        m.index = m.index + pd.Timedelta(minutes=L)
        j = pd.concat([scada10, m], axis=1, join="inner").dropna()
        if len(j) < 500:
            continue
        x, y = j.iloc[:, 0].to_numpy(float), j.iloc[:, 1].to_numpy(float)
        out[L / 60] = np.array([len(x), x.sum(), y.sum(), (x * y).sum(), (x * x).sum(), (y * y).sum()])
    return out


def corr_series(stats: dict[float, np.ndarray]) -> pd.Series:
    r = {}
    for L, (n, sx, sy, sxy, sxx, syy) in stats.items():
        cov, vx, vy = sxy - sx * sy / n, sxx - sx * sx / n, syy - sy * sy / n
        r[L] = cov / np.sqrt(vx * vy)
    return pd.Series(r, dtype=float)


def summarize(s: pd.Series, n: int) -> dict:
    return dict(best_lag_h=round(float(s.idxmax()), 2), r_best=round(float(s.max()), 4),
                r_at5=round(float(s.get(5.0, np.nan)), 4), r_at6=round(float(s.get(6.0, np.nan)), 4), n=int(n))


def continuity_check(turbine: str) -> dict:
    ts = pd.to_datetime(pd.read_csv(FILES[turbine], usecols=["Статистическое время"]).iloc[:, 0],
                        format="%Y-%m-%d %H:%M:%S")
    win = ts[(ts >= "2024-02-29 22:00") & (ts <= "2024-03-01 02:00")]
    return dict(rows=len(win), expect=25, dups_total=int(ts.duplicated().sum()),
                bad_steps=int((win.diff().dropna() != pd.Timedelta("10min")).sum()))


def run(turbines, months):
    monthly, pooled = [], []
    for t in turbines:
        d = load_raw(t, utc=False)  # naive, часы файла
        acc: dict[tuple, dict] = {}
        for m in months:
            e = era5_month(m)
            period = "pre" if pd.Timestamp(m + "-01") < SWITCH else "post"
            lo, hi = e.index.min() - pd.Timedelta("12h"), e.index.max() + pd.Timedelta("12h")
            dm = d[(d.index >= lo) & (d.index <= hi)]
            if len(dm) < 2000:
                continue
            for var, col in PAIRS:
                if col not in e.columns:
                    continue
                st = lag_stats(dm[var], e[col])
                if not st:
                    continue
                s = corr_series(st)
                monthly.append(dict(turbine=t, month=m, period=period, var=var, **summarize(s, st[s.idxmax()][0])))
                a = acc.setdefault((period, var), {})
                for L, v in st.items():
                    a[L] = a.get(L, 0) + v
        for (period, var), st in acc.items():
            s = corr_series(st)
            pooled.append(dict(turbine=t, period=period, var=var, **summarize(s, st[s.idxmax()][0])))
    return pd.DataFrame(monthly), pd.DataFrame(pooled)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--turbine", default="both", choices=["T1", "T2", "both"])
    ap.add_argument("--fetch", nargs="*", default=[], metavar="YYYY-MM", help="докачать месяцы ERA5 (сеть)")
    a = ap.parse_args()

    if a.fetch:
        from research.openmeteo_client import archive_era5
        ERA5_DIR.mkdir(parents=True, exist_ok=True)
        for m in a.fetch:
            f = ERA5_DIR / f"era5_{m}.csv"
            if f.exists():
                print("есть", f.relative_to(REPO))
                continue
            s = pd.Timestamp(m + "-01")
            df = archive_era5(s.strftime("%Y-%m-%d"), (s + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d"))
            df.index = df.index.tz_localize(None)
            df.rename_axis("time").to_csv(f)
            print("сохранён", f.relative_to(REPO), df.shape)

    months = sorted(p.stem.split("_", 1)[1] for p in ERA5_DIR.glob("era5_*.csv"))
    if not months:
        print(f"нет data/era5/era5_YYYY-MM.csv (ожидается в {ERA5_DIR.relative_to(REPO)})")
        return 1
    turbines = ["T1", "T2"] if a.turbine == "both" else [a.turbine]
    print(f"месяцы ERA5: {months}\nтурбины: {turbines}\n")

    print("=== непрерывность 10-мин строк вокруг 2024-03-01 00:00 (ожидание: 25 строк, 0 дублей) ===")
    for t in turbines:
        print(f"  {t}: {continuity_check(t)}")

    monthly, pooled = run(turbines, months)
    pd.set_option("display.width", 200)
    print("\n=== по месяцам: best lag = часы файла минус UTC; r_at5 / r_at6 — corr при лаге ровно 5 ч / 6 ч ===")
    print(monthly.to_string(index=False))
    print("\n=== pooled по периодам (pre = до 2024-03-01, post = после) ===")
    print(pooled.to_string(index=False))

    w = pooled[pooled["var"] == "ws"]
    wm = monthly[monthly["var"] == "ws"]
    out = wm[(wm.best_lag_h < OK_RANGE[0]) | (wm.best_lag_h > OK_RANGE[1])]
    if len(out):
        print(f"\nмесяцы с пиком ветра вне {OK_RANGE} (грубый 0.25° грид ERA5, разница r@5/r@6 в них < 0.02):")
        print(out.to_string(index=False))
    ok = (w.best_lag_h.between(*OK_RANGE).all() and set(w.period) == {"pre", "post"}
          and (wm.r_at6 > wm.r_at5).mean() >= 0.75)
    print(f"\nдоля месяцев с r@6 > r@5 по ветру: {(wm.r_at6 > wm.r_at5).mean():.0%}")
    print("ВЕРДИКТ:", "часы SCADA = фиксированный UTC+6 (Etc/GMT-6) на всём периоде; перехода на UTC+5 в марте 2024 нет "
          "(pooled-пик и до, и после ~6 ч; при переходе post-пик сидел бы на ~5 ч)."
          if ok else f"pooled-пик ветра вне {OK_RANGE} или мало окон с r@6 > r@5 — смотреть таблицы.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

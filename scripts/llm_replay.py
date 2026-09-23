"""Тот же replay, что `make backtest`, но решения принимает LLM-планировщик (OpenAI через Pydantic AI).

    OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m scripts.llm_replay --window test

Прогоны пишутся в runs/llm/<window>/ (сабмит не трогаем). Каждое решение LLM сравнивается с решением
детерминированных правил из runs/backtest/<модель>/<window>/ — отчёт в reports/llm_replay_<window>.csv и .md:
совпадение решений, откаты на правила (fallback), токены.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from windagent.agent.planner import OpenAIPlanner
from windagent.backtest import AGENT_RUNS, PRIMARY_MODEL, ROOT, run_window_agent

LLM_RUNS = ROOT / "runs/llm"
REPORTS = ROOT / "reports"
# USD за 1M токенов, standard tier; https://developers.openai.com/api/docs/pricing (проверено 23.09.2026)
PRICES = {"gpt-5.4-mini": (0.75, 4.50)}


def decision(run_dir: Path) -> dict:
    d = json.loads((run_dir / "decision.json").read_text())
    step = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()][7]
    tokens = step.get("tokens") or {}
    return {"publish": d["publish"], "reason": d["reason"], "reissue": d["reissue_recommended"],
            "summary_ru": d["summary_ru"], "fallback_reason": d.get("fallback_reason"),
            "model_id": d.get("model_id"), "input_tokens": tokens.get("input", 0), "output_tokens": tokens.get("output", 0)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", default="test", choices=["test", "dev"])
    ap.add_argument("--report-only", action="store_true", help="пересобрать отчёт из готовых runs/llm без вызовов LLM")
    args = ap.parse_args()
    root = LLM_RUNS / args.window
    if not args.report_only:
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY не задан (.env)")
        _, _, root = run_window_agent(args.window, PRIMARY_MODEL, planner=OpenAIPlanner(), out_root=LLM_RUNS)
    scripted_root = AGENT_RUNS / PRIMARY_MODEL / args.window
    rows = []
    for run_dir in sorted(root.iterdir()):
        llm = decision(run_dir)
        ref_dir = scripted_root / run_dir.name
        ref = decision(ref_dir) if ref_dir.exists() else {}
        rows.append({"run": run_dir.name, "llm_reason": llm["reason"], "rules_reason": ref.get("reason"),
                     "llm_publish": llm["publish"], "rules_publish": ref.get("publish"),
                     "agree": llm["reason"] == ref.get("reason") and llm["publish"] == ref.get("publish"),
                     "fallback_reason": llm["fallback_reason"], "model_id": llm["model_id"],
                     "input_tokens": llm["input_tokens"], "output_tokens": llm["output_tokens"],
                     "summary_ru": llm["summary_ru"]})
    df = pd.DataFrame(rows)
    REPORTS.mkdir(exist_ok=True)
    csv = REPORTS / f"llm_replay_{args.window}.csv"
    df.to_csv(csv, index=False)
    n, agree, fallback = len(df), int(df.agree.sum()), int(df.fallback_reason.notna().sum())
    tin, tout = int(df.input_tokens.sum()), int(df.output_tokens.sum())
    model_id = df.model_id.dropna().iloc[0] if df.model_id.notna().any() else "—"
    price_in, price_out = PRICES.get(model_id, (None, None))
    cost = None if price_in is None else (tin * price_in + tout * price_out) / 1e6
    cost_row = "—" if cost is None else f"${cost:.3f} (≈ ${cost / max(n, 1):.4f} за решение; ${price_in}/${price_out} за 1M токенов)"
    md = REPORTS / f"llm_replay_{args.window}.md"
    md.write_text(
        f"# LLM-планировщик на окне `{args.window}`\n\n"
        f"Модель: `{model_id}` (OpenAI, Pydantic AI). Прогоны: [`runs/llm/{args.window}/`](../runs/llm/{args.window}).\n\n"
        f"| Показатель | Значение |\n|---|---|\n"
        f"| Решений LLM | {n} |\n"
        f"| Совпало с детерминированными правилами | {agree} из {n} |\n"
        f"| Откатов на правила (ошибка или непроверяемый ответ LLM) | {fallback} |\n"
        f"| Токены, вход / выход | {tin:,} / {tout:,} |\n"
        f"| В среднем на решение | {tin // max(n, 1):,} / {tout // max(n, 1):,} |\n"
        f"| Стоимость | {cost_row} |\n\n"
        "Прогноз мощности в обоих режимах один и тот же (его считает модель, а не LLM). LLM решает, публиковать ли "
        "выпуск и нужен ли пересчёт, и пишет объяснение для диспетчера; ссылаться он может только на ран, прошедший "
        "проверку доступности, иначе выпуск откатывается на правила.\n\n"
        "## Расхождения с правилами\n\n"
        + ("Нет.\n" if agree == n else "| Выпуск | LLM | Правила | Откат |\n|---|---|---|---|\n" + "".join(
            f"| `{r.run}` | {r.llm_reason} | {r.rules_reason} | {r.fallback_reason or '—'} |\n" for r in df.loc[~df.agree].itertuples()))
        + "\n## Примеры объяснений LLM\n\n"
        + "\n".join(f"- `{r.run}` · `{r.llm_reason}` — {r.summary_ru}" for r in df.head(4).itertuples()) + "\n"
    )
    print(f"{n} decisions, agree {agree}/{n}, fallback {fallback}, tokens {tin}/{tout}, cost {cost_row} -> {csv.name}, {md.name}")


if __name__ == "__main__":
    main()

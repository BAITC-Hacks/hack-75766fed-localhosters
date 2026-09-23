import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from windagent.agent.runtime import run_issue


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Auditable wind forecast issue runner")
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("--at", required=True, help="UTC issue time, e.g. 2026-01-31T18:00Z")
    issue.add_argument("--llm", choices=["scripted", "openai"], default=os.getenv("LLM_MODE", "scripted"))
    issue.add_argument("--demo", action="store_true", help="Explicit synthetic weather and illustrative curve")
    issue.add_argument("--cache", type=Path)
    issue.add_argument("--output", type=Path, default=Path("runs"))
    issue.add_argument("--model-adapter", help="module:function implementing the LOC-12 contract")
    backtest = commands.add_parser("backtest")
    backtest.add_argument("--window", choices=["test", "dev", "feb2025"], default="test")
    backtest.add_argument("--llm", choices=["scripted", "openai"], default="scripted")
    backtest.add_argument("--model", choices=["v0", "v1"], default=None, help="default: v1 (WINDAGENT_MODEL)")
    args = parser.parse_args()
    try:
        if args.command == "backtest":
            from windagent.backtest import run_and_write
            planner = None
            if args.llm == "openai":
                from windagent.agent.planner import OpenAIPlanner
                planner = OpenAIPlanner()
            from windagent.backtest import PRIMARY_MODEL
            paths = run_and_write(args.window, args.model or PRIMARY_MODEL, planner=planner)
            print(*paths)
            return 0
        planner = None
        if args.llm == "openai":
            from windagent.agent.planner import OpenAIPlanner
            planner = OpenAIPlanner()
        cache = args.cache or Path("tests/fixtures/nwp" if args.demo else "data/nwp_cache/single_runs/ecmwf_ifs")
        result = run_issue(datetime.fromisoformat(args.at.replace("Z", "+00:00")), cache, args.output,
                           demo=args.demo, planner=planner, model_adapter=args.model_adapter)
        print(result)
    except (ValueError, OSError, ImportError) as error:
        print(f"windagent: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

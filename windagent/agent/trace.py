import json
from time import perf_counter


class Trace:
    def __init__(self):
        self.rows = []

    def call(self, tool, args, action, summarize=lambda value: value):
        start = perf_counter()
        try:
            result = action()
        except Exception as error:
            self.add(tool, args, {"error": str(error)}, "abort", str(error), start)
            raise
        self.add(tool, args, summarize(result), "continue", "Validated tool result", start)
        return result

    def add(self, tool, args, result, decision, rationale, start=None):
        self.rows.append({
            "step": len(self.rows) + 1, "tool": tool, "args": args,
            "result_summary": result, "decision": decision, "rationale": rationale,
            "ms": round((perf_counter() - start) * 1000, 3) if start else 0,
            "tokens": {"input": 0, "output": 0},
        })

    def write(self, path):
        path.write_text("".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in self.rows))

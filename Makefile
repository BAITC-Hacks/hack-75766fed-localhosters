.PHONY: setup verify demo dashboard dashboard-build docker data train backtest backtest-v0 backtest-dev

setup:
	uv sync --frozen

verify:
	LLM_MODE=scripted OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m scripts.verify
	OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m scripts.verify_backtest

demo:
	uv run --frozen python -m windagent issue --at 2026-01-31T18:00Z --llm scripted --demo
	uv run --frozen python -m windagent issue --at 2026-01-31T20:00Z --llm scripted --demo

dashboard: dashboard/node_modules/.package-lock.json
	uv run --frozen python -m scripts.export_dashboard
	cd dashboard && npm run dev -- --host 127.0.0.1

dashboard-build: dashboard/node_modules/.package-lock.json
	uv run --frozen python -m scripts.export_dashboard
	cd dashboard && npm run build

dashboard/node_modules/.package-lock.json: dashboard/package-lock.json
	cd dashboard && npm ci --ignore-scripts

docker:
	docker build -t windagent .

backtest-v0:
	OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m windagent backtest --window test --llm scripted

backtest-dev:
	OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m windagent backtest --window dev --llm scripted

# Owned by LOC-8/10/17; fail explicitly until those adapters land.
data train:
	@echo "$@ adapter pending: LOC-8 (data), LOC-10 (train), LOC-17 (backtest). See docs/research/decisions.md."
	@exit 2

backtest: backtest-v0

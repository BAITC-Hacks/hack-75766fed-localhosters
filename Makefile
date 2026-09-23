.PHONY: setup verify demo llm-replay dashboard dashboard-build docker data train train-v1 train-quantiles backtest backtest-v0 backtest-dev

setup:
	uv sync --frozen

verify:
	LLM_MODE=scripted OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m scripts.verify
	OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m scripts.verify_backtest

demo:
	uv run --frozen python -m windagent issue --at 2026-01-31T18:00Z --llm scripted --demo
	uv run --frozen python -m windagent issue --at 2026-01-31T20:00Z --llm scripted --demo

# Тот же replay февраля, но решения принимает LLM (нужен OPENAI_API_KEY в .env); ~2.5 мин, ~$0.1.
llm-replay:
	OPEN_METEO_CACHE_ONLY=1 uv run --frozen --env-file .env python -m scripts.llm_replay --window test

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

train:
	OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m windagent.model.quantiles

train-v1:
	OPEN_METEO_CACHE_ONLY=1 uv run --frozen python -m windagent.model.v1

train-quantiles: train

# LOC-8 adapter remains separate from the LOC-10 training command.
data:
	@echo "data adapter pending; the committed hourly SCADA parquet is used by train"
	@exit 2

backtest: backtest-v0

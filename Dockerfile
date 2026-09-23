FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY windagent ./windagent
COPY scripts ./scripts
COPY tests/fixtures ./tests/fixtures
COPY research ./research
COPY data/nwp ./data/nwp
COPY models ./models
COPY data/nwp_cache/previous_runs_nov2025_jan2026/ecmwf_ifs.json ./data/nwp_cache/previous_runs_nov2025_jan2026/ecmwf_ifs.json
COPY data/nwp_cache/single_runs/ecmwf_ifs ./data/nwp_cache/single_runs/ecmwf_ifs
COPY ["task context/", "task context/"]
RUN uv sync --frozen --no-dev
ENV LLM_MODE=scripted OPEN_METEO_CACHE_ONLY=1
CMD ["sh", "-c", "uv run --frozen python -m scripts.verify && uv run --frozen python -m scripts.verify_backtest"]

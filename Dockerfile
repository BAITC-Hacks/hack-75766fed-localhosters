FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# LightGBM wheel for Linux links libgomp.so.1 (OpenMP), which the slim image lacks
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY windagent ./windagent
COPY scripts ./scripts
COPY tests/fixtures ./tests/fixtures
COPY research ./research
COPY models ./models
# Whole committed archive (24 MB): as-issued Single Runs, Previous Runs and hourly SCADA used by v1
COPY data ./data
COPY ["task context/", "task context/"]
RUN uv sync --frozen --no-dev
ENV LLM_MODE=scripted OPEN_METEO_CACHE_ONLY=1
CMD ["sh", "-c", "uv run --frozen python -m scripts.verify && uv run --frozen python -m scripts.verify_backtest"]

# Python tooling / app container. Runs Alembic migrations, seed/verify scripts, and
# hosts the FastAPI ranking service (foryou.web.app, served by the `api` compose service).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Cache the sentence-transformers model download on a mounted volume (see
    # docker-compose.yml) so `run --rm` doesn't re-fetch ~90 MB each time.
    HF_HOME=/opt/hf-cache

WORKDIR /app

# Install dependencies first for better layer caching. The project itself is
# installed in editable mode against the mounted source. `--torch-backend=cpu`
# pulls the CPU-only torch wheel (no GPU in Compose) instead of the multi-GB CUDA
# build; the `uv pip` interface ignores [tool.uv.sources], so this flag is the lever.
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --torch-backend=cpu --editable ".[dev,train,web,persona]"

# Source, migrations, scripts and tests are bind-mounted by compose at runtime.
CMD ["bash"]

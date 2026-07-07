# Python tooling / app container. Runs Alembic migrations, seed and verify
# scripts now; hosts the FastAPI ranking service in a later slice.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first for better layer caching. The project itself is
# installed in editable mode against the mounted source.
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --editable ".[dev]"

# Source, migrations, scripts and tests are bind-mounted by compose at runtime.
CMD ["bash"]

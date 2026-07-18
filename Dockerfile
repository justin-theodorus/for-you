# Python tooling / app container. Runs Alembic migrations, seed/bootstrap scripts, and
# hosts the FastAPI ranking service (foryou.web.app).
#
# Three stages, one file:
#   web    — builds the Vite SPA to /web/dist
#   final  — the production serving image (default target): API + the built SPA, no dev deps
#   dev    — final + [dev,train] against the bind-mounted source; what Compose targets, so
#            `make test/check/train` keep working with no second dep set to drift.

# --- Stage 1: build the SPA ------------------------------------------------------------
FROM node:20-bookworm-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./

# Empty (not unset) -> client.ts's `?? "http://localhost:8000"` does NOT fire, so the app
# issues same-origin relative requests. The API serves this bundle itself, so there is no
# cross-origin base URL to point at.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# --- Stage 2: the production serving image ---------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS final

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # The sentence-transformers cache. Baked into the image below (rather than a mounted
    # volume as in Compose), which is what keeps the deployed app stateless.
    HF_HOME=/opt/hf-cache

WORKDIR /app

# Install dependencies first for better layer caching. `--torch-backend=cpu` pulls the
# CPU-only torch wheel instead of the multi-GB CUDA build; the `uv pip` interface ignores
# [tool.uv.sources], so this flag is the lever. No [dev,train] here: the serving path never
# trains (the artifact is committed and copied in below) and never imports sklearn.
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --torch-backend=cpu --editable ".[web,persona]"

# Bake the embedding model into the image so no request ever pays the ~90 MB download. The
# live-trigger path (plan.md §8) embeds inline on the request path; a cold fetch there would
# stall the demo's most interesting endpoint.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('all-MiniLM-L6-v2')"

# Alembic and the scripts must be *in* the image: nothing is bind-mounted in production, and
# the release command (`alembic upgrade head`) plus the world bootstrap both run from here.
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

# The trained scorer artifact (plan.md §3). Committed on purpose: default_scorer() falls
# back to HeuristicScorer *silently* when this file is absent, so a deploy without it would
# serve a heuristic feed and look like it worked.
COPY models/scoring_model.json ./models/scoring_model.json

COPY --from=web /web/dist ./web/dist

# Non-root. The dependency install and the model bake both run as root, so hand over /app
# and the HF cache afterwards.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app /opt/hf-cache
USER app

EXPOSE 8000
CMD ["uvicorn", "foryou.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

# --- Stage 3: the local dev image ------------------------------------------------------
FROM final AS dev

USER root
# The test/lint/train toolchain, on top of the serving image — same base, no drift.
RUN uv pip install --system --torch-backend=cpu --editable ".[dev,train,web,persona]"
USER app

# Source, migrations, scripts and tests are bind-mounted by compose at runtime.
CMD ["bash"]

# Local execution image for the Kognit AI HSE LLM API (R15.8, R15.28-R15.29).
#
# Builds on a Python 3.13 runtime, installs the locked non-dev dependency set with
# uv, runs as a non-root user, exposes the configured port and declares a health
# check against GET /health. No secret, .env file or credential file enters any
# layer (R15.28) — secrets are resolved at runtime from the environment or the
# secret store.
FROM python:3.13-slim

# uv is copied from its official distroless image (pinned by digest-free tag here;
# CI pins the exact version).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    KOGNIT_LLM_PORT=8000

WORKDIR /app

# Install dependencies first (better layer caching), from the committed lockfile
# and excluding the dev group (R15.12, R15.32).
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Copy the application source.
COPY src ./src

# Complete the environment install now that the project source is present.
RUN uv sync --locked --no-dev

# Run as a non-root user whose uid is not 0 (R15.8).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER 10001

EXPOSE ${KOGNIT_LLM_PORT}

# The container health check calls GET /health (R15.29).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request,sys; \
u=f\"http://127.0.0.1:{os.environ.get('KOGNIT_LLM_PORT','8000')}/health\"; \
sys.exit(0 if urllib.request.urlopen(u, timeout=5).status==200 else 1)"

# Serve the FastAPI app with uvicorn; the app root path is /llm.
CMD ["sh", "-c", "uv run --no-dev uvicorn src.main:app --host 0.0.0.0 --port ${KOGNIT_LLM_PORT}"]

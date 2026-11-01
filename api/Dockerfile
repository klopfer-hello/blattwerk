# API image. build: locked deps + the package (non-editable) into /app/.venv.
# test: adds the dev tools and runs lint, types and tests (scripts/test.sh).
# runtime: plain Python, non-root, only the venv.
FROM ghcr.io/astral-sh/uv:0.13.1-python3.13-trixie-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM build AS test
COPY tests ./tests
RUN uv sync --frozen --no-editable
CMD ["sh", "-c", "uv run --frozen --no-sync ruff check . && uv run --frozen --no-sync ruff format --check . && uv run --frozen --no-sync mypy && uv run --frozen --no-sync pytest"]

FROM python:3.13.16-slim-trixie AS runtime
RUN useradd --system --uid 10001 --no-create-home app \
 && mkdir /claude && chown 10001 /claude  # a new named volume takes this owner (CLI installed at runtime)
COPY --from=build /app/.venv /app/.venv
ARG VERSION=dev
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 BW_VERSION=$VERSION
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/healthz', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "--factory", "blattwerk.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]

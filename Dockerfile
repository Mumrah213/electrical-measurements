# Deploy with uv. Multi-stage keeps the runtime image small.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

WORKDIR /app

# Install dependencies first (cached unless pyproject/lock change).
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --frozen --no-install-project --no-dev || uv sync --no-install-project --no-dev

# Now install the project itself.
COPY emeas ./emeas
RUN uv sync --no-dev

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app
# Bring the resolved virtualenv and source over from the build stage.
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"

# Real GPIB needs a VISA backend / drivers mounted into the container; the
# dummy backend runs with no extra system packages.
CMD ["python", "-c", "import emeas; print('emeas', emeas.__doc__.splitlines()[0])"]

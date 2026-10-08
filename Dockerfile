FROM python:3.12-slim

# OpenCV and torch need these shared libraries, which the slim image does not ship.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
COPY data/models/ data/models/
RUN mkdir -p data outputs && uv sync --locked --no-dev

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

# Regenerate the data, run the shipped detector over the sequences, score and run the agents.
CMD ["sh", "-c", "shelf-vision generate && shelf-vision detect && shelf-vision eval && shelf-vision run"]

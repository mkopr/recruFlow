FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --all-groups

FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pin via SJCTL_VERSION for reproducibility if needed; cosign isn't installed in
# this image, so signature verification is skipped in favor of the sha256 check
# the installer always performs. The script is downloaded first (rather than
# piped straight into bash) so SJCTL_BIN_DIR/SJCTL_SKIP_COSIGN reach the script's
# own shell instead of only the curl process on the left side of a pipe.
RUN curl -fsSL -o /tmp/install-sjctl.sh \
    https://raw.githubusercontent.com/solid-company/solid-jobs-skills/main/scripts/install-sjctl.sh \
    && SJCTL_BIN_DIR=/usr/local/bin SJCTL_SKIP_COSIGN=1 bash /tmp/install-sjctl.sh \
    && rm /tmp/install-sjctl.sh

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

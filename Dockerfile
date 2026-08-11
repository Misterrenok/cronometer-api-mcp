FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8080

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY scripts ./scripts

RUN uv sync --frozen --no-dev --compile-bytecode \
    && uv pip install "cronometer-mcp==2.0.3" \
    && python scripts/apply_cronometer_hotfix.py /app

EXPOSE 8080

CMD ["cronometer-api-mcp"]

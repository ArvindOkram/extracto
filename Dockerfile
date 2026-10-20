FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[api,postgres]"

# Only the example is baked in; the real site list comes from a secret file (SITES_CONFIG).
COPY config/sites.example.yaml ./config/sites.example.yaml

RUN useradd --create-home extracto && mkdir -p /app/data /app/reports \
    && chown -R extracto /app/data /app/reports
USER extracto

# `serve` listens on $PORT (Render sets it) and refuses a public bind without EXTRACTO_API_KEY.
ENTRYPOINT ["extracto"]
CMD ["serve", "--host", "0.0.0.0"]

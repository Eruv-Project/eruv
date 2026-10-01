# Eruv monitoring server image. Built by docker-compose.yml, which passes the
# repo's contracts/ folder as the extra build context "contracts": ingest
# validates device messages against those schemas (never copied into server/).
#
#   docker compose build          (from server/)

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CONTRACTS_DIR=/srv/contracts

WORKDIR /srv/server

# Dependencies first so code changes do not reinstall them.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y eruv-server \
    && rm -rf app build *.egg-info

COPY --from=contracts . /srv/contracts
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --system --no-create-home --uid 10001 eruv
USER eruv

EXPOSE 8000

# Migrate, then serve with exactly ONE worker: the event bus and the watchdog
# live in-process (KTD11). Proxy headers are trusted from any address because
# port 8000 is reachable only inside the compose network, where Caddy is the
# only client; this lets per-IP rate limits see the real client address.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]

# /health is 200 only while the watchdog loop runs (KTD12).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

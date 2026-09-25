# The hosted API (Cloud Run service) and its jobs (Cloud Run Jobs: migrate, ingest, prune) in one image.
# Firebase Hosting serves the front end, so it is not in the image. See deploy/ and README's "Deploy".
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[ui,postgres,hosted]"

# Hand-maintained game data the ingest job reads (versions.DATA_DIR is relative to the working directory).
COPY data/forever/*.csv data/forever/
COPY data/tbc/*.csv data/tbc/

RUN useradd --system --uid 10001 app
USER app

# Cloud Run sets PORT and puts a proxy in front (Firebase Hosting, then Google's front end).
CMD ["sh", "-c", "exec uvicorn altarmy_profit.api:create_app --factory --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips '*'"]

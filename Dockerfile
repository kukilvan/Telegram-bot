# syntax=docker/dockerfile:1.29@sha256:572cebbc2b15e6f84c077742952674889cb63cd5e9b80abdffcbe587b6f19183
# Everything pinned, so two builds of one commit are the same: the frontend and the base image by digest, the packages by
# requirements.lock with hashes. A newer base image is taken on purpose: the tag and its digest changed here together
FROM python:3.12.16-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_BIND_HOST=0.0.0.0

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . .

# No USER line: the container starts as root only to fix the rights on the mounted data folder, then app.container_start
# drops them (PUID/PGID) and replaces itself with the application
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --start-interval=2s --retries=3 CMD ["python", "-m", "app.healthcheck"]

CMD ["python", "-m", "app.container_start"]

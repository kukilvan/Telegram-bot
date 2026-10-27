FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_BIND_HOST=0.0.0.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# No USER line: the container starts as root only to fix the rights on the mounted data folder, then app.container_start
# drops them (PUID/PGID) and replaces itself with the application
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD ["python", "-m", "app.healthcheck"]

CMD ["python", "-m", "app.container_start"]

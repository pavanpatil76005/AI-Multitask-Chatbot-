FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip check
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN useradd --create-home appuser \
    && chmod +x ./docker-entrypoint.sh
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/database', timeout=3)"]
CMD ["./docker-entrypoint.sh"]

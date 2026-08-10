FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RAASCAL_DB_PATH=/app/data/raascal_watch.db \
    RAASCAL_WATCHLIST_PATH=/app/config/watchlist.yaml

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["raascal-watch", "serve", "--host", "0.0.0.0", "--port", "8000"]

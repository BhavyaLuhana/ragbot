FROM python:3.11-slim

WORKDIR /app

# Copy shared first for better layer caching
COPY shared /app/shared
COPY services/ingestion /app/services/ingestion

RUN pip install --no-cache-dir -e /app/shared -e /app/services/ingestion

EXPOSE 8001
CMD ["uvicorn", "ingestion.app:app", "--host", "0.0.0.0", "--port", "8001"]
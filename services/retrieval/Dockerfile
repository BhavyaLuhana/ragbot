FROM python:3.11-slim

WORKDIR /app

# System deps for sentence-transformers/torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy shared first for layer caching
COPY shared /app/shared
COPY services/retrieval /app/services/retrieval

RUN pip install --no-cache-dir -e /app/shared -e /app/services/retrieval

EXPOSE 8002
CMD ["uvicorn", "retrieval.app:app", "--host", "0.0.0.0", "--port", "8002"]
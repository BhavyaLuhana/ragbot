FROM python:3.11-slim

WORKDIR /app

COPY shared /app/shared
COPY services/chat /app/services/chat

RUN pip install --no-cache-dir -e /app/shared -e /app/services/chat

EXPOSE 8003
CMD ["uvicorn", "chat.app:app", "--host", "0.0.0.0", "--port", "8003"]
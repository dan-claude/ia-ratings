# Stage 1: build the React client
FROM node:20-slim AS client-builder
WORKDIR /client
COPY client/package.json ./
RUN npm install
COPY client/ ./
RUN npm run build

# Stage 2: Python server
FROM python:3.12-slim
WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ server/
COPY --from=client-builder /client/dist client/dist

ENV PYTHONPATH=/app
# Production WSGI server. One worker process on purpose: SQLite and the in-memory
# login rate limiter both expect a single process; threads give concurrency.
# --timeout 0: never kill a worker for a slow request (admin sync can take minutes).
# Access logging is left off because the app already logs every request.
CMD exec gunicorn --workers 1 --threads 8 --timeout 0 \
    --bind 0.0.0.0:${PORT:-5000} "server.app:create_app()"

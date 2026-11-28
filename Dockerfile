# Stage 1: build the React client
FROM node:20-slim AS client-builder
WORKDIR /client
# The lockfile is copied and `npm ci` used so every build installs exactly the
# reviewed dependency versions.
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

# Stage 2: Python server
FROM python:3.12-slim
WORKDIR /app

# Unprivileged user the server runs as (see docker-entrypoint.sh for why the container
# itself starts as root). /data is where the Railway volume is mounted.
RUN useradd --system --uid 10001 --user-group --no-create-home app \
    && mkdir /data && chown app:app /data

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ server/
# Admin CLI (print_db.py) for use via `railway ssh`; stdlib + server code only.
COPY tools/ tools/
COPY --from=client-builder /client/dist client/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# TRUSTED_PROXY_HOPS=1: Railway puts one reverse proxy in front of the app, so the
# client address comes from X-Forwarded-For (the login rate limit is per client).
ENV PYTHONPATH=/app \
    DB_PATH=/data/app.db \
    TRUSTED_PROXY_HOPS=1

ENTRYPOINT ["docker-entrypoint.sh"]
# Production WSGI server. One worker process on purpose: SQLite and the in-memory
# login rate limiter both expect a single process; threads give concurrency.
# --timeout 120: a worker that stops responding for 2 minutes is restarted. (The title lookup after an
# import runs in a background thread, so no request needs longer than that.)
# Access logging is left off because the app already logs every request.
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:${PORT:-5000} \"server.app:create_app()\""]

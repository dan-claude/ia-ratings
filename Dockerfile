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
CMD python3 -m server.app --no-debug --host 0.0.0.0 --port ${PORT:-5000}

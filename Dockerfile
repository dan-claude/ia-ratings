FROM python:3.12-slim

# Install Node.js 20
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# Install and build React client
COPY client/package.json client/
RUN cd client && npm install
COPY client/ client/
RUN cd client && npm run build

# Copy server source
COPY server/ server/

CMD PYTHONPATH=. python3 -m server.app --no-debug --host 0.0.0.0 --port ${PORT:-5000}

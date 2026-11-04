FROM python:3.8-slim-buster

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    curl \
    ca-certificates \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Node for fp.js (fingerprintjs2 hash execution)
# Debian buster's nodejs is old but sufficient for `node -e`
RUN node --version && npm --version

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create runtime dirs (script already does this, but belt & suspenders)
RUN mkdir -p solver-db logs

# Optional: mount these at runtime
VOLUME ["/app/solver-db", "/app/logs"]

CMD ["python", "-u", "account_creator.py"]

FROM python:3.10-slim

# Install Node.js and system dependencies required for image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    curl \
    ca-certificates \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create runtime directories
RUN mkdir -p solver-db logs

# Persist logs and solver database
VOLUME ["/app/solver-db", "/app/logs"]

# Default port for the API and Web Console
EXPOSE 5000

# Set default environment variables for the container
ENV MODE=api
ENV PORT=5000
ENV CREATE_WORKERS=4

# Start the unified application
CMD ["python", "-u", "account_creator.py"]

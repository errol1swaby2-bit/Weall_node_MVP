# ================================================================
#  WeAll Protocol — Production Dockerfile
# ================================================================

FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential libssl-dev libffi-dev python3-dev git curl \
        sqlite3 iproute2 netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------
# Install dependencies
# ---------------------------------------------------------------
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------
# Copy application
# ---------------------------------------------------------------
COPY . /app

# ---------------------------------------------------------------
# Expose ports and defaults
# ---------------------------------------------------------------
EXPOSE 8080

# ---------------------------------------------------------------
# Healthcheck & entrypoint
# ---------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -f http://localhost:8080/healthz || exit 1

CMD ["uvicorn", "weall_node.weall_api:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

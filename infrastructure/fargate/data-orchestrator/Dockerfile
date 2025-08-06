FROM python:3.11-slim

# Build arguments for version tracking and cache busting
ARG VERSION=unknown
ARG BUILD_DATE=unknown
ARG COMMIT_SHA=unknown
ARG CACHEBUST=1

# Add labels for better image management
LABEL maintainer="LumiSignals Team" \
      version="${VERSION}" \
      build_date="${BUILD_DATE}" \
      commit_sha="${COMMIT_SHA}"

# Set working directory
WORKDIR /app

# Install system dependencies (rarely change)
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching (change less frequently than code)
COPY requirements.txt .

# Install Python dependencies with timeout and retry resilience
RUN pip install \
    --default-timeout=100 \
    --retries 3 \
    --no-cache-dir \
    --index-url https://pypi.org/simple \
    --trusted-host pypi.org \
    -r requirements.txt

# Create non-root user for security (before copying code)
RUN useradd --create-home --shell /bin/bash app

# Copy application code (changes most frequently - do this LAST)
# Use CACHEBUST to force rebuild of this layer when needed
RUN echo "Cache bust: ${CACHEBUST}"
COPY src/ ./src/

# Create version file for deployment verification
RUN echo "Version: ${VERSION}" > /app/version.txt && \
    echo "Build Date: ${BUILD_DATE}" >> /app/version.txt && \
    echo "Commit: ${COMMIT_SHA}" >> /app/version.txt && \
    echo "Cache Bust: ${CACHEBUST}" >> /app/version.txt

# Set ownership
RUN chown -R app:app /app
USER app

# Set environment variables
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    VERSION=${VERSION} \
    BUILD_DATE=${BUILD_DATE} \
    COMMIT_SHA=${COMMIT_SHA}

# Health check with curl (more reliable than python requests)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Run the data orchestrator
CMD ["python", "-m", "src.main"]
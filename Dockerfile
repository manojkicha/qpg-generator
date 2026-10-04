# Build stage
FROM python:3.11-slim-bookworm AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies for weasyprint, paddleocr, and opencv
# weasyprint requires pango, cairo, etc.
# paddleocr/opencv require libgl1 and other shared libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    python3-dev \
    libpango1.0-dev \
    libharfbuzz-dev \
    libpangoft2-1.0-0 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/appuser/.local/bin:${PATH}"

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN useradd -m appuser
USER appuser
WORKDIR /home/appuser/app

# Copy installed python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appuser . .

# Expose port
EXPOSE 8000

# Command to run the application
CMD ["python", "app/main.py"]

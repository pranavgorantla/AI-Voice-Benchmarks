FROM python:3.11-slim

WORKDIR /app

# Install system audio utilities (for audio playback in live trial mode)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

# Copy source
COPY . .

# Generate placeholder audio if not already present
RUN python -m scripts.seed_audio

# Expose FastAPI port
ENV PORT=8000
EXPOSE 8000

CMD ["python", "-m", "src.api.main"]

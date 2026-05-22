FROM python:3.11-slim

WORKDIR /app

# OpenCV runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download YOLO model weights into the image
RUN python -c "from ultralytics import YOLO; YOLO('yolo11s.pt')"

# Copy application source
COPY . .

EXPOSE 5000

# Single worker + 4 threads — required because the YOLO detector runs as a background thread
CMD ["gunicorn", "--worker-class=gthread", "--workers=1", "--threads=4", "--bind=0.0.0.0:5000", "--timeout=120", "app:app"]

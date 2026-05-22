FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Install Python 3.11 and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common curl && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-dev python3-pip \
    libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3

# PyTorch with CUDA 12.1 — installed before ultralytics so it uses GPU build
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download YOLO model weights into the image
RUN python -c "from ultralytics import YOLO; YOLO('yolo11s.pt')"

# Copy application source
COPY . .

EXPOSE 5000

# Single worker + 4 threads — required because the YOLO detector runs as a background thread
CMD ["gunicorn", "--worker-class=gthread", "--workers=1", "--threads=4", "--bind=0.0.0.0:5000", "--timeout=120", "app:app"]

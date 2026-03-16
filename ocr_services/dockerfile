# ============================================================
# Dockerfile cho OCR System (API + Worker dùng chung image)
# ============================================================

FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

# ─────────────────────────────────────────────────────────
# Environment variables
# ─────────────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Ho_Chi_Minh

# CUDA Environment
ENV CUDA_HOME=/usr/local/cuda-11.8
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
ENV TRITON_PTXAS_PATH=${CUDA_HOME}/bin/ptxas

# vLLM & PyTorch settings
ENV VLLM_USE_V1=0
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
ENV TORCH_CUDA_ARCH_LIST="8.6"

# ─────────────────────────────────────────────────────────
# Cài đặt Python 3.12 và system dependencies
# ─────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    curl \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    build-essential \
    cmake \
    ninja-build \
    git \
    wget \
    tesseract-ocr \
    tesseract-ocr-vie \
    poppler-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libmupdf-dev \
    mupdf-tools \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
#
# ─────────────────────────────────────────────────────────
# Set Python 3.12 as default + cài pip bằng get-pip.py
# ─────────────────────────────────────────────────────────
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && pip install --upgrade pip setuptools wheel

WORKDIR /app

# ─────────────────────────────────────────────────────────
# Cài PyTorch với CUDA 11.8
# ─────────────────────────────────────────────────────────
RUN pip install --no-cache-dir \
    torch==2.6.0+cu118 \
    torchvision==0.21.0+cu118 \
    torchaudio==2.6.0+cu118 \
    --index-url https://download.pytorch.org/whl/cu118

# ─────────────────────────────────────────────────────────
# Cài vLLM wheel
# ─────────────────────────────────────────────────────────
RUN mkdir -p /tmp/wheels
COPY wheels/vllm*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/vllm*.whl \
    && rm -rf /tmp/wheels

# ─────────────────────────────────────────────────────────
# Cài xformers
# ─────────────────────────────────────────────────────────
RUN pip install --no-cache-dir xformers==0.0.29.post2 \
    --index-url https://download.pytorch.org/whl/cu118

# Cài flash-attn (THÊM ĐOẠN NÀY)
# ─────────────────────────────────────────────────────────
RUN pip install --no-cache-dir flash-attn==2.7.3 --no-build-isolation

# ─────────────────────────────────────────────────────────
# Cài requirements còn lại
# ─────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────
# Copy source code
# ─────────────────────────────────────────────────────────
COPY . .

RUN mkdir -p /app/uploads /app/outputs

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
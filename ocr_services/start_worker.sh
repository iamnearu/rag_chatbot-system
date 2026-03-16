#!/bin/bash

# ═══════════════════════════════════════════════════════════════════
# Start Celery Worker - Local Development
# ═══════════════════════════════════════════════════════════════════

cd /home/cuongnh/cuong/ocr_services

# Load local environment (commented - sẽ dùng export trực tiếp)
# export $(cat .env.local | grep -v '^#' | xargs)

# Activate conda
source /mnt/hdd1tb/miniconda3/etc/profile.d/conda.sh
conda activate deepseek-ocr2

# Set PYTHONPATH
export PYTHONPATH=/home/cuongnh/cuong/ocr_services:$PYTHONPATH

# Override database URLs để dùng localhost
export DATABASE_URL="postgresql+psycopg2://ocr_cuong:ocr_cuong@localhost:5432/ocr_cuong_db"
export RABBIT_URL="amqp://guest:guest@localhost:5672/"
export REDIS_URL="redis://:infini_rag_flow@localhost:6379/0"
export MINIO_ENDPOINT="http://localhost:9000"

# Start Celery Worker
echo "🔧 Starting Celery Worker..."
echo "   Queue: celery (xử lý OCR tasks)"
echo "   Concurrency: 1 worker (GPU)"
echo ""
echo "⚠️  Lưu ý: Consumer queue_uploads chạy riêng bằng start_consumer.sh"
echo ""

celery -A app.core.celery_app worker \
    -Q celery \
    --loglevel=info \
    --concurrency=1
#
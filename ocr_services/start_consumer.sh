#!/bin/bash
# Start Queue Consumer - Lắng nghe queue_uploads từ RabbitMQ
# Sử dụng: source ./start_consumer.sh

set -e

cd /home/cuongnh/cuong/ocr_services

# Activate conda
source /mnt/hdd1tb/miniconda3/etc/profile.d/conda.sh
conda activate Vllm

# Set PYTHONPATH
export PYTHONPATH=/home/cuongnh/cuong/ocr_services:$PYTHONPATH

# Override URLs để dùng localhost
export DATABASE_URL="postgresql+psycopg2://ocr_cuong:ocr_cuong@localhost:5432/ocr_cuong_db"
export RABBIT_URL="amqp://guest:guest@localhost:5672/"
export REDIS_URL="redis://:infini_rag_flow@localhost:6379/0"
export MINIO_ENDPOINT="localhost:9000"
#
echo "═════════════════════════════════════════════════════════════"
echo "🚀 Starting RabbitMQ Queue Consumer"
echo "═════════════════════════════════════════════════════════════"
echo ""
echo "Configuration:"
echo "  - Queue listen: queue_uploads (nhận message)"
echo "  - Queue publish: queue_finished (gửi kết quả)"
echo "  - Bucket Input: document-uploads"
echo "  - Bucket Output: ocr-results"
echo ""
echo "Flow:"
echo "  1. Nhận raw JSON từ queue_uploads"
echo "  2. Parse message → Dispatch Celery task"
echo "  3. Celery worker xử lý OCR"
echo ""
echo "═════════════════════════════════════════════════════════════"
echo ""

# Run consumer
python -m workers.queue_consumer

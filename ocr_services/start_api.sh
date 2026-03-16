#!/bin/bash

# ═══════════════════════════════════════════════════════════════════
# Start API Server - Local Development
# ═══════════════════════════════════════════════════════════════════

cd /home/cuongnh/cuong/ocr_services

# Load local environment (sử dụng dotenv thay vì export)
# export $(cat .env.local | grep -v '^#' | xargs)

# Activate conda
source $(conda info --base)/etc/profile.d/conda.sh
conda activate deepseek-ocr2
#
# Set PYTHONPATH
export PYTHONPATH=/home/cuongnh/cuong/ocr_services:$PYTHONPATH

# Override database URLs để dùng localhost
export DATABASE_URL="postgresql+psycopg2://ocr_cuong:ocr_cuong@localhost:5432/ocr_cuong_db"
export RABBIT_URL="amqp://guest:guest@localhost:5672/"
export REDIS_URL="redis://:infini_rag_flow@localhost:6379/0"
export MINIO_ENDPOINT="http://localhost:9000"

# Start API
echo "🚀 Starting API Server..."
echo "   API: http://localhost:8001"
echo "   Docs: http://localhost:8001/docs"
echo ""

python -m app.main

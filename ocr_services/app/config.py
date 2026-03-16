# configs/config.py (hoặc app/core/config.py)

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ═══════════════════════════════════════════════════════════════════
# MODEL SETTINGS (DeepSeek-OCR-2 Architecture)
# ═══════════════════════════════════════════════════════════════════
BASE_SIZE = 1024
IMAGE_SIZE = 768
CROP_MODE = True
MIN_CROPS = 2
MAX_CROPS = 6
MAX_CONCURRENCY = 32
NUM_WORKERS = 64
PRINT_NUM_VIS_TOKENS = False
SKIP_REPEAT = True
#
# Đọc từ biến môi trường
MODEL_PATH = os.getenv('MODEL_PATH', '')

# ═══════════════════════════════════════════════════════════════════
# OCR ENGINE SETTINGS
# ═══════════════════════════════════════════════════════════════════
# OCR_ENGINE is defined in the OCR ENGINE SELECTION section below
# Valid options: 'auto', 'deepseek', 'mineru', 'docling'

# ═══════════════════════════════════════════════════════════════════
# INPUT/OUTPUT PATHS
# ═══════════════════════════════════════════════════════════════════
# Base directory của project (ocr_services)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INPUT_PATH = os.getenv('INPUT_PATH', os.path.join(BASE_DIR, 'uploads'))
OUTPUT_PATH = os.getenv('OUTPUT_PATH', os.path.join(BASE_DIR, 'outputs'))
UPLOAD_PATH = os.getenv('UPLOAD_PATH', os.path.join(BASE_DIR, 'uploads'))

# ═══════════════════════════════════════════════════════════════════
# MINIO SETTINGS
# ═══════════════════════════════════════════════════════════════════
# Đọc từ biến môi trường
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost:9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', '')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', '')

# Bucket cho file input (PDF từ upload service)
MINIO_INPUT_BUCKET = os.getenv('MINIO_INPUT_BUCKET', 'document-uploads')

# Bucket cho file output (kết quả OCR)
MINIO_OUTPUT_BUCKET = os.getenv('MINIO_OUTPUT_BUCKET', 'ocr-results')

# Legacy - để tương thích code cũ (alias cho OUTPUT bucket)
MINIO_BUCKET_NAME = MINIO_OUTPUT_BUCKET

# ═══════════════════════════════════════════════════════════════════
# DATABASE & MESSAGE QUEUE
# ═══════════════════════════════════════════════════════════════════
DATABASE_URL = os.getenv('DATABASE_URL', '')

# RabbitMQ - clean up URL
raw_rabbit = os.getenv('RABBIT_URL', '')
RABBIT_URL = (raw_rabbit.strip().rstrip('/') + '/') if raw_rabbit else ''

# RabbitMQ Queue Names
QUEUE_UPLOADS = os.getenv('RABBIT_QUEUE_UPLOADS', 'queue_uploads')   # Queue nhận message upload
QUEUE_FINISHED = os.getenv('RABBIT_QUEUE_FINISHED', 'queue_finished') # Queue gửi kết quả sau xử lý

# Redis (dùng cho Celery result backend)
REDIS_URL = os.getenv('REDIS_URL', '')

# ═══════════════════════════════════════════════════════════════════
# OTHER SETTINGS
# ═══════════════════════════════════════════════════════════════════
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '200'))

# Prompt với instruction ngôn ngữ Vietnamese rõ ràng
# Giúp model focus vào tiếng Việt, giảm output tiếng Trung
PROMPT = '<image>\n<|grounding|>Convert the document to markdown.'

# Prompt backup không có language instruction (nếu cần)
PROMPT_SIMPLE = '<image>\n<|grounding|>Convert the document to markdown.'

_IMAGE_TOKEN = "<image>"
CHUNK_SIZE = 40

# ═══════════════════════════════════════════════════════════════════
# IMAGE PREPROCESSING SETTINGS
# ═══════════════════════════════════════════════════════════════════
# DPI khi render PDF → image (cao hơn = rõ dấu hơn, nhưng chậm hơn)
# 144 = default cũ, 200 = recommended cho Vietnamese diacritics
OCR_DPI = int(os.getenv('OCR_DPI', '200'))

# Bật/tắt chỉnh nghiêng ảnh (deskew)
DESKEW_ENABLED = os.getenv('DESKEW_ENABLED', 'true').lower() == 'true'

# Bật/tắt image enhancement (CLAHE + sharpen) để cải thiện dấu tiếng Việt
IMAGE_ENHANCE_ENABLED = os.getenv('IMAGE_ENHANCE_ENABLED', 'true').lower() == 'true'

# Số pixel crop mỗi cạnh để loại bỏ viền/margin (0 = không crop)
CROP_MARGIN_PIXELS = int(os.getenv('CROP_MARGIN_PIXELS', '60'))

# ═══════════════════════════════════════════════════════════════════
# OCR ENGINE SELECTION
# ═══════════════════════════════════════════════════════════════════
# Chọn engine chính: "auto", "deepseek", "mineru", hoặc "docling"
# 
# "auto" (mặc định):
#   - PDF >2MB: MinerU (tốc độ, tóm tắt tốt)
#   - PDF <2MB: Deepseek (chi tiết, fine-grained)
#   - Image: Deepseek (OCR optimized)
#   - Fallback: Docling nếu engine chính bị lỗi
#
# Cố định engine: "deepseek", "mineru", "docling"
#   - Dùng engine cố định cho tất cả files
#   - Fallback: Docling nếu engine chính bị lỗi
#
OCR_ENGINE = os.getenv('OCR_ENGINE', 'deepseek').lower()
if OCR_ENGINE not in ['auto', 'deepseek', 'mineru', 'docling']:
    raise ValueError(f"Invalid OCR_ENGINE: {OCR_ENGINE}. Must be 'auto', 'deepseek', 'mineru', or 'docling'")

# Ngưỡng file size cho auto selection (MB)
AUTO_ENGINE_SIZE_THRESHOLD_MB = float(os.getenv('AUTO_ENGINE_SIZE_THRESHOLD_MB', '2.0'))

def select_engine_for_file(file_path: str) -> str:
    """
    Chọn engine phù hợp dựa trên file size (chỉ dùng khi OCR_ENGINE='auto')
    
    Logic:
    - PDF > 2MB → MinerU (nhanh, tốt cho tài liệu dài)
    - PDF ≤ 2MB → DeepSeek (chi tiết, fine-grained)
    - Fallback → Docling
    
    Returns: 'deepseek', 'mineru', hoặc 'docling'
    """
    if OCR_ENGINE != 'auto':
        return OCR_ENGINE
    
    try:
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        
        if file_size_mb > AUTO_ENGINE_SIZE_THRESHOLD_MB:
            return 'mineru'
        else:
            return 'deepseek'
    except Exception:
        # Fallback nếu không đọc được file
        return 'deepseek'

# ═══════════════════════════════════════════════════════════════════
# VLLM SERVER SETTINGS (from MinerU)
# ═══════════════════════════════════════════════════════════════════
VLLM_MODEL_PATH = os.getenv('VLLM_MODEL_PATH', '')
VLLM_PORT = int(os.getenv('VLLM_PORT', '30000'))
VLLM_GPU_MEMORY_FRACTION = float(os.getenv('VLLM_GPU_MEMORY_FRACTION', '0.9'))
VLLM_DTYPE = os.getenv('VLLM_DTYPE', 'float16')  # 'float16', 'float32', 'bfloat16'
VLLM_MAX_MODEL_LEN = int(os.getenv('VLLM_MAX_MODEL_LEN', '4096'))
VLLM_USE_V1 = int(os.getenv('VLLM_USE_V1', '1'))  # 0 or 1
OMP_NUM_THREADS = int(os.getenv('OMP_NUM_THREADS', '1'))

# Custom Logits Processors
VLLM_CUSTOM_LOGITS_PROCESSORS = os.getenv('VLLM_CUSTOM_LOGITS_PROCESSORS', 'false').lower() == 'true'

# ═══════════════════════════════════════════════════════════════════
# TOKENIZER INITIALIZATION
# ═══════════════════════════════════════════════════════════════════
try:
    from transformers import AutoTokenizer
    TOKENIZER = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    print(f"✅ Tokenizer loaded from: {MODEL_PATH}")
except Exception as e:
    TOKENIZER = None
    print(f"⚠️ Không load được Tokenizer DeepSeek: {e}. Worker sẽ chạy ở chế độ dự phòng.")
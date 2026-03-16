from celery import Celery
from app.config import RABBIT_URL, REDIS_URL, QUEUE_UPLOADS

#
celery_app = Celery(
    "ocr_system",
    broker=RABBIT_URL,
    backend=REDIS_URL,
    # QUAN TRỌNG: Trỏ chính xác vào module tasks theo cấu trúc mới
    include=['app.tasks.tasks'] 
)

# Cấu hình tối ưu cho DeepSeek-OCR và tránh lỗi kết nối
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Ho_Chi_Minh',
    enable_utc=True,
#
    # --- TASK TIMEOUTS (increased for model loading) ---
    task_soft_time_limit=6000,  # 100 minutes soft timeout (warning before hard timeout)
    task_time_limit=6600,  # 110 minutes hard timeout (kill task)
    
    # --- CHỐNG LỖI MẤT KẾT NỐI ---
    broker_heartbeat=0,
    broker_connection_timeout=60,
    event_queue_expires=60,
    worker_prefetch_multiplier=1,
    
    # --- QUEUE SETTINGS ---
    # Tất cả Celery tasks đều dùng queue 'celery' mặc định
    # Queue 'queue_uploads' chỉ dùng cho external service gửi message (xử lý bởi queue_consumer.py)
    task_default_queue='celery',
    task_default_exchange='celery',
    task_default_routing_key='celery',
    
    # Task routing - tất cả tasks đều vào queue celery
    task_routes={
        'tasks.consume_minio_document_message': {'queue': 'celery'},
        'tasks.process_ocr_from_minio': {'queue': 'celery'},
        'tasks.process_ocr_document': {'queue': 'celery'},
        'tasks.process_ocr_with_model': {'queue': 'celery'},
    },
    
    # --- CẤU HÌNH CẢNH BÁO ---
    worker_cancel_long_running_tasks_on_connection_loss=True,
)
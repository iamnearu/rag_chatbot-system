# ═══════════════════════════════════════════════════════════════════
# STANDARD LIBRARY (LIGHTWEIGHT)
# ═══════════════════════════════════════════════════════════════════
import logging
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════════
# PROJECT IMPORTS
# ═══════════════════════════════════════════════════════════════════
from app.core.celery_app import celery_app

# ═══════════════════════════════════════════════════════════════════
# HEAVY/LAZY IMPORTS (import bên trong hàm khi cần)
# - app.services.ocr_service (import bên trong hàm task)
# - torch, vllm (GPU/ML frameworks)
# ═══════════════════════════════════════════════════════════════════

"""
Output của nó chỉ xuất hiện khi bạn gọi logger.info(), error(), warning(), debug()
 Bản thân dòng này không in gì cả.
"""
logger = logging.getLogger(__name__)

#Hàm task sẽ nhận thêm tham số self
#đăng ký hàm này như một task với tên "tasks.process_ocr_document" có quyền truy cập vào self 
@celery_app.task(
    bind=True, 
    name="tasks.process_ocr_document",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
)
def process_ocr_document_task(self, job_id: str):
    """
    Task Celery để điều phối xử lý OCR.
    """#
    try:
        # 1. Đảm bảo môi trường Python tìm thấy các module trong dự án
        project_root = os.getcwd() # get current working directory
        if project_root not in sys.path:
            sys.path.insert(0, project_root) #them thu mục vào đầu danh sách
            
        # 2. Import logic xử lý thực tế
        from app.services.ocr_service import process_job_with_multi_env
        
        logger.info(f"=== [CELERY START] Nhận Job ID: {job_id} ===")
        
        # 3. Cập nhật trạng thái Task (tùy chọn - giúp hiển thị trên dashboard)
        self.update_state(state='PROGRESS', meta={'job_id': job_id})
        
        # 4. Gọi "trái tim" của hệ thống xử lý
        from app.config import OCR_ENGINE
        result = process_job_with_multi_env(job_id, model=OCR_ENGINE)
        
        logger.info(f"=== [CELERY SUCCESS] Hoàn thành Job ID: {job_id} ===")
        return f"SUCCESS: {result}"
        
    except Exception as exc:
        # Ghi log chi tiết lỗi bao gồm cả dòng lỗi trong worker.py
        logger.error(f"CELERY ERROR] Lỗi khi thực hiện Job {job_id}: {exc}", exc_info=True)
        # Thông báo cho Celery rằng task này đã thất bại
        return f"FAILED: {str(exc)}"


@celery_app.task(bind=True, name="tasks.process_ocr_with_model")
def process_ocr_with_model_task(self, job_id: str, model: str):
    """
     NEW TASK - Xử lý OCR với model được chỉ định
    Sử dụng Multi-Environment Executor để chạy trong conda env tương ứng
    
    Args:
        job_id: ID của job
        model: Tên model (deepseek, mineru, docling)
    """
    try:
        # Setup paths
        project_root = os.getcwd()
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        
        logger.info(f"=== [CELERY MULTI-ENV] Job ID: {job_id}, Model: {model} ===")
        
        # Update state
        self.update_state(state='PROGRESS', meta={'job_id': job_id, 'model': model})
        
        # Import dependencies
        from app.services.ocr_service import process_job_with_multi_env
        
        # Execute trong conda environment tương ứng
        result = process_job_with_multi_env(job_id, model)
        
        logger.info(f"=== [CELERY MULTI-ENV SUCCESS] Job {job_id} completed ===")
        return f"SUCCESS: {result}"
        
    except Exception as exc:
        logger.error(
            f"[CELERY MULTI-ENV ERROR] Job {job_id}, Model {model}: {exc}", 
            exc_info=True
        )
        return f"FAILED: {str(exc)}"


# ═══════════════════════════════════════════════════════════════════
# NEW TASKS: MinIO + RabbitMQ Flow
# ═══════════════════════════════════════════════════════════════════

@celery_app.task(bind=True, name="tasks.consume_minio_document_message")
def consume_minio_document_message_task(self, message: dict):
    """
    Task 1: Luôn chạy - Lắng nghe & xử lý message từ RabbitMQ
    
    Nhận message khi document được upload lên MinIO:
    {
        "document_id": "uuid-cua-document",
        "filename": "ten-file-goc.pdf",
        "minio_object_name": "uuid-cua-document/ten-file-goc.pdf",
        "minio_uri": "minio://...",
        "status": "uploaded"
    }
    
    Flow:
    1. Tạo OCRJob mới trong DB (job_id = document_id - ĐỘNG)
    2. Dispatch task process_ocr_from_minio với job_id
    3. Return job_id cho client (nếu cần)
    
    Args:
        message: Dict nhận từ RabbitMQ
    """
    try:
        project_root = os.getcwd()
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        
        from app.services.document_consumer import create_ocr_job_from_minio_message
        
        logger.info(f"=== [MINIO CONSUMER] Nhận message từ RabbitMQ ===")
        logger.info(f"Message content: {message}")
        
        # Bước 1: Tạo OCRJob trong DB (job_id động = document_id)
        job_id = create_ocr_job_from_minio_message(message)
        
        # Bước 2: Dispatch task xử lý
        # Job id là động từ message
        minio_object_name = message.get("minio_object_name")
        
        logger.info(f"📤 Dispatching process_ocr_from_minio task")
        logger.info(f"   - Job ID: {job_id}")
        logger.info(f"   - MinIO object: {minio_object_name}")
        
        # Gửi task đến queue để xử lý bất đồng bộ
        process_ocr_from_minio_task.delay(job_id, minio_object_name)
        
        logger.info(f"✅ Successfully created job {job_id} from MinIO message")
        return {
            "status": "success",
            "job_id": job_id,
            "message": f"Job created and queued for processing"
        }
        
    except Exception as exc:
        logger.error(f"❌ [MINIO CONSUMER ERROR] {exc}", exc_info=True)
        return {
            "status": "failed",
            "message": f"Error: {str(exc)}"
        }


@celery_app.task(
    bind=True, 
    name="tasks.process_ocr_from_minio",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
)
def process_ocr_from_minio_task(self, job_id: str, minio_object_name: str):
    """
    Task xử lý OCR từ file trên MinIO
    
    Flow:
    1. Kiểm tra job status - chỉ xử lý nếu PENDING
    2. Download file từ MinIO (bucket: document-uploads)
    3. Xử lý OCR
    4. Upload kết quả lên MinIO (bucket: ocr-results)
    5. Update DB với URLs
    
    Args:
        job_id: ID của job (động từ message)
        minio_object_name: Path trong MinIO bucket (e.g., "job_id/file.pdf")
    """
    try:
        project_root = os.getcwd()
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        
        from app.utils.minio_helper import MinIOHelper
        from app.services.document_consumer import update_job_status
        from app.models.documents import JobStatus, OCRJob
        from app.config import UPLOAD_PATH, OUTPUT_PATH
        from app.services.ocr_service import process_job_with_multi_env
        from app.core.database import SessionLocal
        
        logger.info(f"=== [MINIO OCR PROCESSOR] Bắt đầu xử lý Job {job_id} ===")
        logger.info(f"MinIO object: {minio_object_name}")
        
        # Bước 1: Kiểm tra job status - CHỈ XỬ LÝ NẾU PENDING
        db = SessionLocal()
        job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
        db.close()
        
        if not job:
            error_msg = f"Job {job_id} not found"
            logger.error(f"❌ {error_msg}")
            return f"FAILED: {error_msg}"
        
        if job.status != JobStatus.PENDING:
            logger.info(f"⏭️ Job {job_id} đã có status={job.status.value} - SKIP")
            return f"SKIPPED: Job already processed with status {job.status.value}"
        
        # Update state cho Celery dashboard
        self.update_state(state='PROGRESS', meta={'job_id': job_id, 'stage': 'downloading'})
        
        # Bước 2: Download từ MinIO vào /tmp (nhẹ hơn, auto-cleanup)
        logger.info(f"📥 Downloading file từ MinIO...")
        minio_helper = MinIOHelper()
        
        # Dùng /tmp thay vì ./uploads để giảm tải disk
        import tempfile
        filename = minio_object_name.split('/')[-1]
        local_path = os.path.join(tempfile.gettempdir(), f"ocr_{job_id}_{filename}")
        
        # Download từ input bucket
        success = minio_helper.download_input(minio_object_name, local_path)
        
        if not success:
            error_msg = f"Failed to download {minio_object_name} from MinIO"
            logger.error(f"❌ {error_msg}")
            update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            
            # Gửi message FAILED vào queue_finished
            from app.services.rabbitmq_publisher import publish_job_finished
            publish_job_finished(job_id, "failed", error=error_msg)
            
            return f"FAILED: {error_msg}"
        
        logger.info(f"✅ Downloaded successfully to {local_path}")
        
        # Bước 3: Update status to RUNNING
        update_job_status(job_id, JobStatus.RUNNING, input_path=local_path)
        
        # Update state - đang xử lý
        self.update_state(state='PROGRESS', meta={'job_id': job_id, 'stage': 'processing'})
        
        # Bước 4: Xử lý OCR (bao gồm upload lên MinIO trong ocr_service.py)
        logger.info(f"🔄 Processing OCR...")
        from app.config import OCR_ENGINE
        result = process_job_with_multi_env(job_id, model=OCR_ENGINE)
        
        # NOTE: ocr_service.py đã upload kết quả lên MinIO rồi
        # Chỉ cần lấy URLs để update DB và gửi notification
        
        output_dir = os.path.join(OUTPUT_PATH, job_id)
        
        # Generate MinIO URLs (đã được upload bởi ocr_service.py)
        from app.config import MINIO_ENDPOINT, MINIO_BUCKET_NAME
        base_url = f"minio://{MINIO_BUCKET_NAME}"
        result_urls = {
            "markdown_url": f"{base_url}/{job_id}/{job_id}.md",
            "json_url": f"{base_url}/{job_id}/{job_id}.json"
        }
        
        # Bước 5: Gửi message SUCCESS vào queue_finished
        from app.services.rabbitmq_publisher import publish_job_finished
        publish_job_finished(job_id, "success", result_urls=result_urls)
        #
        # Bước 6: Cleanup - Xóa file tạm để giải phóng disk
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                logger.info(f"🗑️ Cleaned up temp file: {local_path}")
            # Xóa output folder local (đã upload lên MinIO rồi)
            if os.path.exists(output_dir):
                import shutil
                shutil.rmtree(output_dir)
                logger.info(f"🗑️ Cleaned up output dir: {output_dir}")
        except Exception as cleanup_err:
            logger.warning(f"⚠️ Cleanup warning: {cleanup_err}")
        
        logger.info(f"✅ [MINIO OCR PROCESSOR SUCCESS] Job {job_id} completed")
        return {
            "status": "success",
            "job_id": job_id,
            "result_urls": result_urls
        }
        
    except Exception as exc:
        logger.error(f"❌ [MINIO OCR PROCESSOR ERROR] Job {job_id}: {exc}", exc_info=True)
        
        # Update status to FAILED
        try:
            from app.services.document_consumer import update_job_status
            from app.models.documents import JobStatus
            update_job_status(job_id, JobStatus.FAILED, error=str(exc))
            
            # Gửi message FAILED vào queue_finished
            from app.services.rabbitmq_publisher import publish_job_finished
            publish_job_finished(job_id, "failed", error=str(exc))
        except:
            pass
        
        return f"FAILED: {str(exc)}"
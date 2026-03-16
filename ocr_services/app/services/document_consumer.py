"""
Document Consumer Service - Xử lý message từ RabbitMQ khi document được upload lên MinIO
Luồng:
1. Nhận message từ RabbitMQ: {document_id, filename, minio_object_name, ...}
2. Tạo OCRJob mới trong DB với job_id = document_id (động)
3. Dispatch Celery task: process_ocr_from_minio(job_id, minio_object_name)
"""

# ═══════════════════════════════════════════════════════════════════
# STANDARD LIBRARY (LIGHTWEIGHT)
# ═══════════════════════════════════════════════════════════════════
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

# ═══════════════════════════════════════════════════════════════════
# PROJECT IMPORTS
# ═══════════════════════════════════════════════════════════════════
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.documents import OCRJob, JobStatus
from app.schemas.schemas import MinIODocumentMessage

# ═══════════════════════════════════════════════════════════════════
# HEAVY/LAZY IMPORTS (import bên trong hàm khi cần)
# - pika (RabbitMQ)
# - minio (MinIO SDK)
# ═══════════════════════════════════════════════════════════════════

_log = logging.getLogger(__name__)


def get_db_session() -> Session:
    """Tạo session kết nối database."""
    return SessionLocal()


def create_ocr_job_from_minio_message(message: Dict[str, Any]) -> str:
    """
    Tạo OCRJob mới trong DB từ MinIO message
    
    Args:
        message: Dict với keys: document_id, filename, minio_object_name, minio_uri, status
        
    Returns:
        job_id (document_id)
        
    Raises:
        ValueError: Nếu message không hợp lệ
    """
    try:
        # Validate message
        parsed_message = MinIODocumentMessage(**message)
        
        db = get_db_session()
        
        # Job ID = document_id (động từ upload service)
        job_id = parsed_message.document_id
        
        # Kiểm tra job đã tồn tại chưa
        existing_job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
        if existing_job:
            _log.warning(f"Job {job_id} already exists in DB, skipping creation")
            db.close()
            return job_id
        
        # Tạo OCRJob mới
        ocr_job = OCRJob(
            job_id=job_id,
            filename=parsed_message.filename,
            # input_path sẽ được set là MinIO URI (hoặc temporary path sau download)
            input_path=parsed_message.minio_object_name,  # Lưu object name tạm thời
            status=JobStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            ocr_model="auto",  # Default model (sẽ auto-detect dựa file size)
        )
        
        db.add(ocr_job)
        db.commit()
        
        _log.info(f"✅ Created OCRJob {job_id} from MinIO message")
        _log.info(f"   - Filename: {parsed_message.filename}")
        _log.info(f"   - MinIO object: {parsed_message.minio_object_name}")
        _log.info(f"   - Status: PENDING")
        
        db.close()
        return job_id
 #       
    except ValueError as e:
        _log.error(f"❌ Invalid MinIO message format: {e}")
        raise
    except Exception as e:
        _log.error(f"❌ Error creating OCRJob from MinIO message: {e}", exc_info=True)
        raise


def update_job_status(job_id: str, status: JobStatus, **kwargs) -> None:
    """
    Update trạng thái job trong DB
    
    Args:
        job_id: ID của job
        status: JobStatus mới
        **kwargs: Các field khác để update (e.g., num_pages=10, processing_time=5.5)
    """
    db = get_db_session()
    
    try:
        job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
        
        if not job:
            _log.error(f"Job {job_id} not found in DB")
            return
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        
        job.status = status
        job.updated_at = datetime.now(timezone.utc)
        
        db.add(job)
        db.commit()
        
        _log.info(f"✅ Updated job {job_id} status to {status.value}")
        
    except Exception as e:
        _log.error(f"❌ Error updating job status: {e}", exc_info=True)
    finally:
        db.close()


def get_job_info(job_id: str) -> Dict[str, Any]:
    """
    Lấy thông tin chi tiết của job
    
    Args:
        job_id: ID của job
        
    Returns:
        Dict với thông tin job, hoặc None nếu không tìm thấy
    """
    db = get_db_session()
    
    try:
        job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
        
        if not job:
            return None
        
        return {
            "job_id": job.job_id,
            "filename": job.filename,
            "status": job.status.value,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "num_pages": job.num_pages,
            "processing_time": job.processing_time,
            "error": job.error,
            "result_path": job.result_path,
            "minio_json_url": job.minio_json_url,
        }
        
    except Exception as e:
        _log.error(f"❌ Error retrieving job info: {e}", exc_info=True)
        return None
    finally:
        db.close()

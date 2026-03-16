"""
OCR API Routes - Clean version
"""
import os
import uuid
import json
import shutil
import logging
import pika
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from enum import Enum
from io import BytesIO

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.schemas.schemas import (
    OCRResponse, 
    DocumentResponseSchema,
    JobStatus as SchemaJobStatus,
)
from app.core.database import get_db, SessionLocal
from app.models.documents import OCRJob, JobStatus
from app.config import (
    UPLOAD_PATH, 
    MAX_UPLOAD_MB, 
    QUEUE_UPLOADS,
    RABBIT_URL,
    REDIS_URL,
    MINIO_INPUT_BUCKET,
)
from app.utils.minio_helper import get_minio_helper

_log = logging.getLogger(__name__)

ocr_router = APIRouter(prefix="/api/v1/ocr", tags=["OCR"])


class OCRModelType(str, Enum):
    AUTO = "auto"
    DEEPSEEK = "deepseek"
    MINERU = "mineru"
    DOCLING = "docling"


def _safe_filename(name: str) -> str:
    return Path(name).name


# =============================================================================
# HEALTH CHECK
# =============================================================================

@ocr_router.get("/health")
def health_check():
    """Health check - Kiểm tra trạng thái các services"""
    health = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {}
    }
    
    # Check Database
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        health["services"]["database"] = "connected"
    except Exception as e:
        health["services"]["database"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    # Check MinIO
    try:
        minio = get_minio_helper()
        minio.client.list_buckets()
        health["services"]["minio"] = "connected"
    except Exception as e:
        health["services"]["minio"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    # Check RabbitMQ
    try:
        params = pika.URLParameters(RABBIT_URL)
        conn = pika.BlockingConnection(params)
        conn.close()
        health["services"]["rabbitmq"] = "connected"
    except Exception as e:
        health["services"]["rabbitmq"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    # Check Redis
    try:
        import redis
        r = redis.from_url(REDIS_URL)
        r.ping()
        health["services"]["redis"] = "connected"
    except Exception as e:
        health["services"]["redis"] = f"error: {str(e)}"
        health["status"] = "degraded"
    
    return health


# =============================================================================
# RESULT & STATUS
# =============================================================================

@ocr_router.get("/result/{job_id}", response_model=DocumentResponseSchema)
def get_result(job_id: str, db: Session = Depends(get_db)):
    """Lấy kết quả OCR - trả về URLs download từ MinIO"""
    job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    
    markdown_url = None
    json_url = None
    
    if job.status == JobStatus.SUCCESS:
        minio = get_minio_helper()
        markdown_url = minio.get_result_url(job_id, "md")
        json_url = minio.get_result_url(job_id, "json")
    
    return DocumentResponseSchema(
        job_id=job.job_id,
        status=SchemaJobStatus(job.status.value),
        num_pages=job.num_pages,
        processing_time=job.processing_time,
        markdown_url=markdown_url,
        json_url=json_url,
        error=job.error,
    )


@ocr_router.get("/status/{job_id}")
def get_status(job_id: str, db: Session = Depends(get_db)):
    """Check status nhanh - polling friendly"""
    job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "model": job.ocr_model,
        "num_pages": job.num_pages,
        "processing_time": job.processing_time,
        "error": job.error
    }


@ocr_router.get("/download/{job_id}/{file_type}")
def download_result(job_id: str, file_type: str, db: Session = Depends(get_db)):
    """Lấy presigned URL để download (md hoặc json)"""
    if file_type not in ["md", "json"]:
        raise HTTPException(status_code=400, detail="file_type phải là 'md' hoặc 'json'")
    
    job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    
    if job.status != JobStatus.SUCCESS:
        raise HTTPException(status_code=400, detail=f"Job chưa xong. Status: {job.status.value}")
    
    minio = get_minio_helper()
    url = minio.get_result_url(job_id, file_type)
    
    if not url:
        raise HTTPException(status_code=404, detail=f"File {file_type} không tồn tại")
    
    return {"job_id": job_id, "file_type": file_type, "download_url": url, "expires_in": "1 hour"}


# =============================================================================
# UPLOAD - PRODUCTION (RabbitMQ Flow)
# =============================================================================

@ocr_router.post("/upload", response_model=OCRResponse)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload qua RabbitMQ flow (Production)
    
    Flow: Upload → MinIO → RabbitMQ → Consumer → Worker → Result
    Dùng với: consumer.sh + worker.sh
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ PDF")

    job_id = uuid.uuid4().hex
    
    try:
        data = await file.read()
        size_mb = round(len(data) / (1024 * 1024), 2)
        
        if size_mb > MAX_UPLOAD_MB:
            raise HTTPException(status_code=413, detail=f"File > {MAX_UPLOAD_MB}MB")
        
        clean_name = _safe_filename(file.filename)
        
        # Upload lên MinIO
        minio = get_minio_helper()
        minio_object_name = f"{job_id}/{clean_name}"
        
        minio.client.put_object(
            bucket_name=MINIO_INPUT_BUCKET,
            object_name=minio_object_name,
            data=BytesIO(data),
            length=len(data),
            content_type="application/pdf"
        )
        
        # Auto-select model
        selected_model = "mineru" if size_mb > 2 else "deepseek"
        
        # Create job
        new_job = OCRJob(
            job_id=job_id,
            filename=clean_name,
            input_path=minio_object_name,
            file_size_mb=size_mb,
            status=JobStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            ocr_model=selected_model
        )
        db.add(new_job)
        db.commit()
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")

    try:
        # Gửi message vào RabbitMQ
        params = pika.URLParameters(RABBIT_URL)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        
        channel.queue_declare(queue=QUEUE_UPLOADS, durable=True)
        
        message = {
            "document_id": job_id,
            "filename": clean_name,
            "minio_object_name": minio_object_name,
            "minio_uri": f"minio://{MINIO_INPUT_BUCKET}/{minio_object_name}",
            "model": selected_model,
            "status": "uploaded"
        }
        
        channel.basic_publish(
            exchange='',
            routing_key=QUEUE_UPLOADS,
            body=json.dumps(message),
            properties=pika.BasicProperties(delivery_mode=2)
        )
        connection.close()
        
    except Exception as e:
        new_job.status = JobStatus.FAILED
        new_job.error = f"Queue Error: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Queue error: {str(e)}")

    return OCRResponse(
        job_id=job_id,
        status=SchemaJobStatus.PENDING,
        message=f"Document queued. Model: {selected_model.upper()}"
    )


# =============================================================================
# PROCESS - TEST/DEV (Celery Direct)
# =============================================================================

@ocr_router.post("/process", response_model=OCRResponse)
async def process_document(
    file: UploadFile = File(...),
    model: OCRModelType = Form(OCRModelType.AUTO),
    db: Session = Depends(get_db)
):
    """
    Upload + chọn model, xử lý trực tiếp qua Celery (Test/Dev)
    
    Flow: Upload → Local → Celery Task → Worker → Result
    Dùng với: worker.sh (không cần consumer)
    
    Models: auto | deepseek | mineru | docling
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ PDF")

    job_id = uuid.uuid4().hex
    
    try:
        data = await file.read()
        size_mb = round(len(data) / (1024 * 1024), 2)
        
        if size_mb > MAX_UPLOAD_MB:
            raise HTTPException(status_code=413, detail=f"File > {MAX_UPLOAD_MB}MB")
        
        clean_name = _safe_filename(file.filename)

        # Save locally
        os.makedirs(UPLOAD_PATH, exist_ok=True)
        saved_path = os.path.join(UPLOAD_PATH, f"{job_id}_{clean_name}")
        
        with open(saved_path, "wb") as f:
            f.write(data)
        
        # Auto-select model
        selected_model = model.value
        if selected_model == "auto":
            selected_model = "mineru" if size_mb > 2 else "deepseek"
        
        # Create job
        new_job = OCRJob(
            job_id=job_id,
            filename=clean_name,
            input_path=saved_path,
            file_size_mb=size_mb,
            status=JobStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            ocr_model=selected_model
        )
        db.add(new_job)
        db.commit()
        
    except HTTPException:
        raise
    except Exception as e:
        if 'saved_path' in locals() and os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(status_code=500, detail=f"Save error: {str(e)}")

    try:
        from app.tasks.tasks import process_ocr_with_model_task
        process_ocr_with_model_task.delay(job_id, selected_model)
        
    except Exception as e:
        new_job.status = JobStatus.FAILED
        new_job.error = f"Task Error: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail="Cannot queue task")

    return OCRResponse(
        job_id=job_id,
        status=SchemaJobStatus.PENDING,
        message=f"Processing started. Model: {selected_model.upper()}"
    )


# =============================================================================
# JOBS MANAGEMENT
# =============================================================================

@ocr_router.get("/jobs")
def list_jobs(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Liệt kê jobs với filter theo status"""
    query = db.query(OCRJob)
    
    if status:
        try:
            status_enum = JobStatus(status.upper())
            query = query.filter(OCRJob.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid status. Valid: {[s.value for s in JobStatus]}"
            )
    
    total = query.count()
    jobs = query.order_by(OCRJob.created_at.desc()).offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "jobs": [
            {
                "job_id": j.job_id,
                "filename": j.filename,
                "status": j.status.value,
                "model": j.ocr_model,
                "file_size_mb": j.file_size_mb,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ]
    }


@ocr_router.delete("/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Xóa job và tất cả dữ liệu liên quan"""
    job = db.query(OCRJob).filter(OCRJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")

    # Xóa trên MinIO
    minio = get_minio_helper()
    minio_result = minio.delete_job_objects(job_id)
    
    # Xóa local files
    if job.output_dir and os.path.exists(job.output_dir):
        try:
            shutil.rmtree(job.output_dir)
        except Exception as e:
            _log.warning(f"Cannot delete output_dir: {e}")

    if job.input_path and os.path.exists(job.input_path):
        try:
            os.remove(job.input_path)
        except Exception as e:
            _log.warning(f"Cannot delete input_path: {e}")

    # Xóa trong DB
    db.delete(job)
    db.commit()

    return {"status": "deleted", "job_id": job_id, "minio": minio_result}

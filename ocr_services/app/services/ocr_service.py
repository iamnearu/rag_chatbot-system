"""
OCR Service với Multi-Environment Support
Xử lý OCR jobs trong các conda environments khác nhau
"""
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.documents import OCRJob, JobStatus
from app.core.multi_env_executor import get_multi_env_executor
from app.config import OUTPUT_PATH, MINIO_ENDPOINT, MINIO_BUCKET_NAME

_log = logging.getLogger(__name__)


def get_db_session() -> Session:
    """Tạo session kết nối database."""
    return SessionLocal()


#allow push args via key value pair ::: Kwargs
def update_job_status(db: Session, job: OCRJob, status: JobStatus, **kwargs) -> None:
    """Update job to Database """
    #iteration over kwargs to set additional fields
    for key, value in kwargs.items():
        if hasattr(job, key): # has attribute
            setattr(job, key, value) #set attribute 
     
    job.status = status
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()


def process_job_with_multi_env(job_id: str, model: str) -> str:
    """
    Xử lý OCR job với model được chỉ định trong conda environment tương ứng
    
    Args:
        job_id: ID của job
        model: Tên model (deepseek, mineru, docling)
        
    Returns:
        Message về kết quả xử lý
    """
    db = get_db_session()
    try:
        job = db.get(OCRJob, job_id)
        
        if not job:
            _log.error(f"Job {job_id} not found")
            return f"Job {job_id} not found"
        
        # Luôn dùng model được truyền vào (mặc định: deepseek)
        _log.info(f"Processing Job {job_id} with Model: {model.upper()}")
        
        # Update status to RUNNING
        update_job_status(db, job, JobStatus.RUNNING, ocr_model=model)
        
        # Setup output directory + name + job id
        output_dir = os.path.join(OUTPUT_PATH, job_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # Get executor
        executor = get_multi_env_executor()
        
        # Execute trong conda environment tương ứng
        _log.info(f"Executing {model} in conda environment...")
        result = executor.execute_in_conda(
            engine_name=model,
            input_path=job.input_path,
            output_dir=output_dir,
            job_id=job_id
        )
        
        # Check result status
        if result.get("status") == "failed":
            raise RuntimeError(result.get("error", "Unknown error"))
        
        # Extract results
        blocks = result.get("blocks", [])
        total_pages = result.get("total_pages", 0)
        
        _log.info(f"{model.upper()} completed. Blocks: {len(blocks)}, Pages: {total_pages}")
        
        # Extract timing data from worker result
        timing = result.get("timing", {})
        if timing:
            _log.info(f"⏱️  Worker timing: {timing}")
        
        # Save results to MinIO (tương tự như ocr_service.py)
        from app.utils.postprocess_md import upload_to_minio
        
        _log.info(f" Uploading results to MinIO...")
        upload_to_minio(output_dir, job_id)
        
        # Generate MinIO URLs
        base_url = f"{MINIO_ENDPOINT}/{MINIO_BUCKET_NAME}/{job_id}"
        minio_urls = {
            "markdown": f"{base_url}/{job_id}.md",
            "json": f"{base_url}/{job_id}.json"
        }
        
        # Update job status to SUCCESS (including timing data)
        update_job_status(
            db, job, JobStatus.SUCCESS,
            num_pages=total_pages,
            result_path=minio_urls['markdown'],
            minio_json_url=minio_urls['json'],
            processing_time=int(timing.get("processing_time", 0)) if timing else None,
            t_pdf2img=timing.get("t_pdf2img"),
            t_preprocess=timing.get("t_preprocess"),
            t_infer=timing.get("t_infer"),
            t_postprocess=timing.get("t_postprocess"),
            ocr_model=model,
        )
        
        # NOTE: Notification sẽ được gửi bởi tasks.py (process_ocr_from_minio_task)
        # Không cần gửi ở đây để tránh duplicate message
        
        _log.info(f"Job {job_id} completed successfully")
        return f"Job {job_id} completed with {model}"
        
    except Exception as e:
        _log.error(f"Error processing Job {job_id}: {e}")
        import traceback
        traceback.print_exc()
        
        # Update job status to FAILED
        try:
            update_job_status(
                db, job, JobStatus.FAILED,
                error=str(e)
            )
        except Exception:
            _log.error(f"Failed to update job status to FAILED for {job_id}")
        
        raise
        
    finally:
        # NOTE: Cleanup input file được xử lý bởi tasks.py (process_ocr_from_minio_task)
        # Không cleanup ở đây để tránh xóa file 2 lần gây crash
        db.close()

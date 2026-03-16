"""
app/models.py
- Định nghĩa bảng ocr_jobs lưu "job state" (trạng thái xử lý).
- Mỗi job là 1 lần upload PDF.
"""
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Integer, Text, Enum, Float
from app.core.database import Base


class JobStatus(enum.Enum):
    """Job status enum - gộp PENDING + QUEUED"""
    PENDING = "PENDING"     # Chờ xử lý (gộp cả pending và queued)
    RUNNING = "RUNNING"     # Đang xử lý
    SUCCESS = "SUCCESS"     # Xử lý thành công
    FAILED = "FAILED"       # Xử lý thất bại
    CANCELLED = "CANCELLED" # Đã hủy (future use)

##
class OCRJob(Base):
    __tablename__ = "ocr_jobs"

    job_id = Column(String, primary_key=True, index=True)

    filename = Column(String, nullable=False)  # Tên file PDF đã upload
    input_path = Column(String, nullable=False)  # Đường dẫn file PDF đã upload

    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)

    created_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=datetime.now(timezone.utc))

    num_pages = Column(Integer, nullable=True)  # Số trang trong PDF
    processing_time = Column(Integer, nullable=True)  # Thời gian xử lý (tính bằng giây)
    error = Column(Text, nullable=True)  # Lỗi nếu có

     # ===== metrics GPU (VRAM) =====
    gpu_name = Column(String, nullable=True)
    gpu_total_mb = Column(Integer, nullable=True)
    vram_peak_mb = Column(Integer, nullable=True)          # peak allocated
    vram_reserved_peak_mb = Column(Integer, nullable=True) # peak reserved

    output_dir = Column(String, nullable=True)  # Đường dẫn thư mục lưu kết quả    
    markdown_path = Column(String, nullable=True)  # Đường dẫn file markdown kết quả
    json_path = Column(String, nullable=True)  # Đường dẫn file json kết quả

    # Bổ sung vào class OCRJob trong models.py
    file_size_mb = Column(Float, nullable=True) 
    
    # Stage timing metrics (giúp debug bước nào đang chậm)
    t_pdf2img = Column(Float, nullable=True)
    t_preprocess = Column(Float, nullable=True)
    t_infer = Column(Float, nullable=True)
    t_postprocess = Column(Float, nullable=True)
    
    # Metadata bổ sung
    is_deleted = Column(Integer, default=0) # 0: active, 1: deleted (soft delete)
    result_path = Column(String, nullable=True) # Lưu link MinIO cho file .md
    minio_json_url = Column(String, nullable=True)    # Lưu link MinIO cho file .json
    
    # Multi-model support
    ocr_model = Column(String, nullable=True) # Model used: deepseek, mineru, docling
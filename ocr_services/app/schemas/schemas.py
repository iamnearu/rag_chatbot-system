from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from enum import Enum


# --- 0. JobStatus Enum (phải khớp với models.documents.JobStatus) ---
class JobStatus(str, Enum):
    """Job status enum - dùng cho cả Schema và Model"""
    PENDING = "PENDING"   # Chờ xử lý (gộp PENDING + QUEUED)
    RUNNING = "RUNNING"   # Đang xử lý
    SUCCESS = "SUCCESS"   # Xử lý thành công
    FAILED = "FAILED"     # Xử lý thất bại
    CANCELLED = "CANCELLED"  # Đã hủy (future use)


# --- 1. Schema cho luồng Upload (Giai đoạn đầu) ---
class OCRResponse(BaseModel):
    job_id: str
    status: JobStatus  # Dùng enum thay vì str
    message: Optional[str] = None

    class Config:
        from_attributes = True  # cho phép nhận dữ liệu từ ORM objects

# --- 2. Định nghĩa các Block nội dung (Dùng cho kết quả chi tiết) ---
class BlockBase(BaseModel):
    type: str
#
#heading với level và text
class HeadingBlock(BlockBase):
    type: str = "heading"
    level: int
    text: str

#đoạn văn
class ParagraphBlock(BlockBase):
    type: str = "paragraph"
    text: str

#bảng biểu
class TableBlock(BlockBase):
    type: str = "table"
    table_id: str
    rows: List[List[str]]
    
#
# --- 3. Định nghĩa Trang, Metadata và Body ---
class ContentPage(BaseModel):
    page_number: int
    # Sử dụng Union để Swagger hiểu được các loại block khác nhau
    blocks: List[Union[HeadingBlock, ParagraphBlock, TableBlock, Any]]

class DocumentMetadata(BaseModel):
    source_filename: str
    total_pages: int
    processed_at: datetime # Chuyển sang datetime để chuẩn hóa

class DocumentBody(BaseModel):
    metadata: DocumentMetadata
    content: List[ContentPage]

# --- 4. Schema Response Cuối cùng (Dùng cho endpoint lấy kết quả) ---
class DocumentResponseSchema(BaseModel):
    """Response khi lấy kết quả OCR - chỉ trả URL, không trả document trực tiếp"""
    job_id: str
    status: JobStatus  # Dùng enum
    num_pages: Optional[int] = None
    processing_time: Optional[float] = None
    # URLs để download kết quả từ MinIO
    markdown_url: Optional[str] = None
    json_url: Optional[str] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "job_id": "uuid-123-456",
                "status": "SUCCESS",
                "num_pages": 10,
                "processing_time": 5.45,
                "markdown_url": "http://minio:9000/ocr-results/uuid-123-456/result.md?...",
                "json_url": "http://minio:9000/ocr-results/uuid-123-456/result.json?...",
                "error": None
            }
        }


# --- 5. Schema cho MinIO Document Message từ RabbitMQ ---
class MinIODocumentMessage(BaseModel):
    """
    Message nhận từ RabbitMQ khi user upload file vào MinIO
    
    Payload từ upload service:
    {
        "document_id": "uuid-cua-document",
        "filename": "ten-file-goc.pdf",
        "minio_object_name": "uuid-cua-document/ten-file-goc.pdf",
        "minio_uri": "minio://document-uploads/uuid-cua-document/ten-file-goc.pdf",
        "status": "uploaded"
    }
    """
    document_id: str  # UUID của document, sẽ dùng làm job_id
    filename: str     # Tên file gốc (e.g., "report.pdf")
    minio_object_name: str  # Path trong MinIO bucket (e.g., "uuid/report.pdf")
    minio_uri: str    # Full URI (e.g., "minio://document-uploads/uuid/report.pdf")
    status: str       # Status từ upload service (e.g., "uploaded")
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "document_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "filename": "sample.pdf",
                "minio_object_name": "a1b2c3d4-e5f6-7890-abcd-ef1234567890/sample.pdf",
                "minio_uri": "minio://document-uploads/a1b2c3d4-e5f6-7890-abcd-ef1234567890/sample.pdf",
                "status": "uploaded"
            }
        }
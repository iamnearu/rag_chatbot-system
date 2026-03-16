"""
MinIO Helper Functions - Xử lý download/upload file từ MinIO

Buckets:
- document-uploads: File input (PDF từ upload service)
- ocr-results: File output (kết quả OCR)
"""

import os
import logging
from pathlib import Path
from typing import Optional, List
from minio import Minio
from app.config import (
    MINIO_ENDPOINT, 
    MINIO_ACCESS_KEY, 
    MINIO_SECRET_KEY,
    MINIO_INPUT_BUCKET,
    MINIO_OUTPUT_BUCKET,
)
#
_log = logging.getLogger(__name__)


class MinIOHelper:
    """
    Helper class cho MinIO operations
    
    Buckets:
    - input_bucket: document-uploads (file PDF đầu vào)
    - output_bucket: ocr-results (kết quả OCR)
    """
    
    def __init__(self):
        """Initialize MinIO client"""
        self.endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
        self.client = Minio(
            self.endpoint,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=False
        )
        # 2 buckets
        self.input_bucket = MINIO_INPUT_BUCKET    # document-uploads
        self.output_bucket = MINIO_OUTPUT_BUCKET  # ocr-results
        
        # Ensure buckets exist
        self._ensure_buckets()
    
    def _ensure_buckets(self):
        """Tạo buckets nếu chưa tồn tại"""
        for bucket in [self.input_bucket, self.output_bucket]:
            try:
                if not self.client.bucket_exists(bucket):
                    self.client.make_bucket(bucket)
                    _log.info(f"✅ Created bucket: {bucket}")
            except Exception as e:
                _log.warning(f"⚠️ Could not check/create bucket {bucket}: {e}")
    
    def download_input(self, object_name: str, local_path: str) -> bool:
        """
        Download file từ INPUT bucket (document-uploads)
        
        Args:
            object_name: Path trong MinIO (e.g. "job_id/document.pdf")
            local_path: Đường dẫn local để lưu file
            
        Returns:
            True nếu thành công
            
        Example:
            >>> helper.download_input("job_123/report.pdf", "./uploads/job_123_report.pdf")
        """
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            _log.info(f"📥 Downloading from {self.input_bucket}: {object_name} → {local_path}")
            
            self.client.fget_object(
                self.input_bucket,
                object_name,
                local_path
            )
            
            _log.info(f"✅ Downloaded successfully: {local_path}")
            return True
            
        except Exception as e:
            _log.error(f"❌ Failed to download {object_name}: {e}")
            return False
    
    def upload_result(self, local_path: str, object_name: str) -> str:
        """
        Upload kết quả lên OUTPUT bucket (ocr-results)
        
        Args:
            local_path: Đường dẫn file local
            object_name: Path trong MinIO (e.g. "job_id/result.md")
            
        Returns:
            MinIO URI nếu thành công, None nếu lỗi
            
        Example:
            >>> uri = helper.upload_result("./outputs/job_123/result.md", "job_123/result.md")
            >>> print(uri)  # "minio://ocr-results/job_123/result.md"
        """
        try:
            if not os.path.exists(local_path):
                _log.error(f"File not found: {local_path}")
                return None
            
            _log.info(f"📤 Uploading to {self.output_bucket}: {local_path} → {object_name}")
            
            self.client.fput_object(
                self.output_bucket,
                object_name,
                local_path
            )
            
            minio_uri = f"minio://{self.output_bucket}/{object_name}"
            _log.info(f"✅ Uploaded successfully: {minio_uri}")
            return minio_uri
            
        except Exception as e:
            _log.error(f"❌ Failed to upload: {e}")
            return None
    
    def upload_job_results(self, job_id: str, output_dir: str) -> dict:
        """
        Upload kết quả của một job lên MinIO (chỉ file cần thiết)
        
        Args:
            job_id: ID của job
            output_dir: Thư mục chứa kết quả local (e.g. "./outputs/job_123/")
            
        Returns:
            Dict với URLs của các file đã upload:
            {
                "markdown_url": "minio://ocr-results/job_id/{job_id}.md",
                "json_url": "minio://ocr-results/job_id/{job_id}.json"
            }
        """
        result_urls = {}
        
        # Chỉ upload 2 file cần thiết: {job_id}.md và {job_id}.json
        md_file = Path(output_dir) / f"{job_id}.md"
        json_file = Path(output_dir) / f"{job_id}.json"
        
        # Upload markdown
        if md_file.exists():
            object_name = f"{job_id}/{job_id}.md"
            uri = self.upload_result(str(md_file), object_name)
            if uri:
                result_urls["markdown_url"] = uri
        
        # Upload JSON
        if json_file.exists():
            object_name = f"{job_id}/{job_id}.json"
            uri = self.upload_result(str(json_file), object_name)
            if uri:
                result_urls["json_url"] = uri
        
        # Upload images directory (parallel)
        images_dir = Path(output_dir) / "images"
        if images_dir.exists() and images_dir.is_dir():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            image_files = [
                img_file for img_file in sorted(images_dir.iterdir())
                if img_file.is_file() and img_file.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
            ]
            
            if image_files:
                image_urls = []
                
                def _upload_image(img_file):
                    object_name = f"{job_id}/images/{img_file.name}"
                    return self.upload_result(str(img_file), object_name)
                
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = {executor.submit(_upload_image, f): f for f in image_files}
                    for future in as_completed(futures):
                        try:
                            uri = future.result()
                            if uri:
                                image_urls.append(uri)
                        except Exception as e:
                            img = futures[future]
                            _log.warning(f"Failed to upload image {img.name}: {e}")
                
                if image_urls:
                    result_urls["image_urls"] = image_urls
                    _log.info(f"📷 Uploaded {len(image_urls)} images for job {job_id} (parallel)")
        
        return result_urls
    
    def get_result_url(self, job_id: str, file_type: str = "md") -> Optional[str]:
        """
        Get presigned URL để download kết quả
        
        Args:
            job_id: ID của job
            file_type: "md" hoặc "json"
            
        Returns:
            Presigned URL (valid 1 hour)
        """
        try:
            from datetime import timedelta
            
            object_name = f"{job_id}/result.{file_type}"
            
            url = self.client.presigned_get_object(
                self.output_bucket,
                object_name,
                expires=timedelta(hours=1)
            )
            return url
            
        except Exception as e:
            _log.error(f"❌ Failed to get presigned URL: {e}")
            return None
    
    def file_exists_input(self, object_name: str) -> bool:
        """Kiểm tra file tồn tại trong input bucket"""
        try:
            self.client.stat_object(self.input_bucket, object_name)
            return True
        except:
            return False
    
    def file_exists_output(self, object_name: str) -> bool:
        """Kiểm tra file tồn tại trong output bucket"""
        try:
            self.client.stat_object(self.output_bucket, object_name)
            return True
        except:
            return False
    
    def delete_job_objects(self, job_id: str) -> dict:
        """
        Xóa tất cả objects của một job trên MinIO (cả input và output buckets)
        
        Args:
            job_id: ID của job
            
        Returns:
            Dict với kết quả xóa:
            {
                "input_deleted": 2,
                "output_deleted": 5,
                "errors": []
            }
        """
        from minio.deleteobjects import DeleteObject
        
        result = {
            "input_deleted": 0,
            "output_deleted": 0,
            "errors": []
        }
        
        # Xóa từ input bucket
        try:
            prefix = f"{job_id}/"
            objects = list(self.client.list_objects(self.input_bucket, prefix=prefix, recursive=True))
            if objects:
                delete_list = [DeleteObject(obj.object_name) for obj in objects]
                errors = list(self.client.remove_objects(self.input_bucket, delete_list))
                result["input_deleted"] = len(delete_list) - len(errors)
                for err in errors:
                    result["errors"].append(f"input/{err.object_name}: {err}")
        except Exception as e:
            result["errors"].append(f"input bucket error: {e}")
        
        # Xóa từ output bucket
        try:
            prefix = f"{job_id}/"
            objects = list(self.client.list_objects(self.output_bucket, prefix=prefix, recursive=True))
            if objects:
                delete_list = [DeleteObject(obj.object_name) for obj in objects]
                errors = list(self.client.remove_objects(self.output_bucket, delete_list))
                result["output_deleted"] = len(delete_list) - len(errors)
                for err in errors:
                    result["errors"].append(f"output/{err.object_name}: {err}")
        except Exception as e:
            result["errors"].append(f"output bucket error: {e}")
        
        _log.info(f"🗑️ Deleted job {job_id}: input={result['input_deleted']}, output={result['output_deleted']}")
        return result
    
    # === LEGACY METHODS (để tương thích code cũ) ===
    
    def download_file(self, object_name: str, local_path: str) -> bool:
        """Legacy: Download từ input bucket"""
        return self.download_input(object_name, local_path)
    
    def upload_file(self, local_path: str, object_name: str) -> bool:
        """Legacy: Upload lên output bucket"""
        uri = self.upload_result(local_path, object_name)
        return uri is not None


# Singleton instance
_minio_helper = None


def get_minio_helper() -> MinIOHelper:
    """Get MinIO helper instance (singleton)"""
    global _minio_helper
    if _minio_helper is None:
        _minio_helper = MinIOHelper()
    return _minio_helper

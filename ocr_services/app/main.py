import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import router từ tầng API và các cấu hình từ core
from app.api.routes.ocr import ocr_router
from app.core.database import Base, engine


#
import os
from app.config import UPLOAD_PATH, OUTPUT_PATH

# Thêm đoạn này vào trước khi khởi tạo FastAPI app
os.makedirs(UPLOAD_PATH, exist_ok=True)
os.makedirs(OUTPUT_PATH, exist_ok=True)
# 1. Khởi tạo Database (Tự động tạo bảng nếu chưa có)
# Lưu ý: Trong môi trường production lớn, sếp có thể yêu cầu dùng Alembic để migration
Base.metadata.create_all(bind=engine)
#
# 2. Khởi tạo ứng dụng FastAPI
app = FastAPI(
    title="EOV OCR Professional Service",
    description="Hệ thống OCR xử lý bất đồng bộ chuẩn kiến trúc phân lớp",
    version="1.0.0"
)

# 3. Cấu hình Middleware (Cần thiết nếu bạn gọi API từ trình duyệt khác domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Đăng ký các Router (Kết nối các "quầy giao dịch" vào hệ thống chính)
# Prefix đã được định nghĩa trong ocr_router là /api/v1/ocr
app.include_router(ocr_router)

# 5. Endpoint kiểm tra sức khỏe hệ thống (Health Check)
@app.get("/", tags=["System"])
async def root():
    return {
        "message": "Welcome to EOV OCR API",
        "status": "online",
        "docs": "/docs"
    }

# 6. Chạy ứng dụng bằng Uvicorn
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True  # Bật reload để tự động cập nhật khi bạn sửa code
    )
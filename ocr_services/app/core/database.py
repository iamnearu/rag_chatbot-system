from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base
from app.config import DATABASE_URL
#
# Thêm cấu hình Pool để tránh lỗi mất kết nối khi treo máy lâu
engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True,      # Kiểm tra kết nối trước khi dùng
    pool_size=10,            # Số lượng kết nối tối đa duy trì
    max_overflow=20,         # Số lượng kết nối vượt mức cho phép
    pool_recycle=3600        # Reset kết nối sau 1 giờ để tránh bị DB ngắt
)
#
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()

def get_db():
    """Tạo session DB cho mỗi request (Dùng cho FastAPI Depends)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        # Với scoped_session, nên dùng remove() thay vì close() 
        # để dọn dẹp triệt để session trong thread hiện tại
        SessionLocal.remove()


from contextlib import contextmanager

@contextmanager
def get_db_context():
    """
    Context manager cho DB session - dùng trong services/tasks (không phải FastAPI).
    
    Usage:
        with get_db_context() as db:
            job = db.get(OCRJob, job_id)
            db.commit()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
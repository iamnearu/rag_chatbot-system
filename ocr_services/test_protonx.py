
import sys
import os
import time

# --- Cấu hình đường dẫn ---
# Thêm thư mục hiện tại vào sys.path để import được app.utils
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from app.utils.vn_model_corrector import correct_with_model, _load_model

    # --- ĐOẠN TEXT CẦN TEST ---
    input_text = """
 TÀI LIỆU QUẢN LÝ BẢO TRÌ HỆ THỐNG ĐIỆN TRONG TÒA NHÀ

(Tài liệu tham khảo)

## MỘ ĐẠU

Tòa nhà chung cư là nơi ở của hàng trăm hộ gia đình, nhất là tại các tòa nhà chung cư lớn có thể chưa dân số lên tới hàng nghìn người. Lúc này tòa nhà nếu muốn vận hành hiệu quả và ổn định thì ban quản lý tòa nhà cần đảm bảo hệ thống điện luôn luôn hoạt động ổn định hiệu quả.

Điều này đổi hơi ban quản lý tòa nhà cần quản lý chặt chẽ và bảo trì hệ thống điện trong tòa nhà thương xuyên, qua đó có thể kịp thời phát hiện sự cố bất ngờ xảy ra cũng như kịp thời xử lý hiệu quả.

Khi quản lý bảo hành bảo trì hệ thống điện trong tòa nhà, ban quản lý cần:

+ Quản lý việc điều khiển, duy trì hoạt động của hệ thống trang thiết bị (hệ thống điện, nước,...) thuộc phần sở hữu chung hoặc phần sử dụng chung của tòa nhà.

+ Thông báo bằng văn bản về những yêu cầu, những điều cần chú ý cho người sử dụng khi bắt đầu sử dụng tòa nhà, hướng dẫn việc lắp đặt các trang thiết bị thuộc phần sở hữu riêng vào hệ thống trang thiết bị dùng chung.

+ Định kỳ kiểm tra cụ thể, chi tiết, bộ phận hệ thống cấp điện, hệ thống điện, hệ thống trang

thiết bị cấp, thoát nước trong và ngoài nhà của tòa nhà.
    """

    print("🚀 Đang tải model (lần đầu sẽ mất vài giây)...")
    t0 = time.time()
    # Gọi hàm _load_model() trước để tách biệt thời gian load và thời gian chạy
    _load_model()
    print(f"✅ Model đã sẵn sàng ({time.time() - t0:.2f}s)")

    print("\n" + "="*40)
    print("VĂN BẢN GỐC:")
    print(input_text.strip())
    print("="*40 + "\n")

    print("🔄 Đang xử lý...")
    t_start = time.time()
    
    # Gọi hàm sửa lỗi chính
    output_text = correct_with_model(input_text)
    
    t_end = time.time()
    process_time = t_end - t_start

    print("="*40)
    print("KẾT QUẢ SỬA LỖI:")
    print(output_text.strip())
    print("="*40)
    
    print(f"\n⏱️ Thời gian xử lý: {process_time:.4f} giây")

except ImportError as e:
    print("❌ Lỗi Import: Không tìm thấy module 'app'. Hãy chắc chắn bạn chạy script này từ thư mục gốc của dự án (ocr_services).")
    print(f"Chi tiết: {e}")
except Exception as e:
    print(f"❌ Lỗi: {e}")
    import traceback
    traceback.print_exc()

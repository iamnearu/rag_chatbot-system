import pytesseract
from PIL import Image
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
# Chú ý đường dẫn import từ utils
from app.utils.postprocess_md import process_single_image
from app.config import NUM_WORKERS

def preprocess_batch(images, prompt):
    """
    Tiền xử lý batch images cho DeepSeek OCR.
    GIỐNG HỆT Deepseek-ocr-customvLLM
    
    Args:
        images: List PIL Images
        prompt: Prompt cho model
    
    Returns:
        Tuple (batch_inputs, processed_images)
        - batch_inputs: List cache_item cho vLLM
        - processed_images: List ảnh đã xử lý (để crop bbox)
    """
    print(f"\n{'🔶'*30}")
    print(f"🚀 [preprocess_batch] Processing {len(images)} images...")
    if images:
        print(f"   First image size: {images[0].size}")
    print(f"{'🔶'*30}\n")
    
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        # results sẽ là danh sách các bộ (cache_item, image) - giống repo gốc
        results = list(tqdm(
            executor.map(lambda image: process_single_image(image, prompt), images),
            total=len(images),
            desc="🚀 Pre-processing images (deskew + crop)",
            leave=False 
        ))
    
    # TÁCH RIÊNG 2 DANH SÁCH TỪ results (giống repo gốc)
    batch_inputs = [r[0] for r in results]       # Input cho vLLM
    processed_images = [r[1] for r in results]   # Ảnh đã xử lý (để crop bbox)
    
    print(f"\n🔶 [preprocess_batch] COMPLETE!")
    print(f"   Processed {len(processed_images)} images")
    if processed_images:
        print(f"   First processed image size: {processed_images[0].size}")
    print(f"{'🔶'*30}\n")
    
    return batch_inputs, processed_images  # Trả về 2 giá trị giống repo gốc

def generate_ocr(llm, batch_inputs, sampling_params):
    """
    Chạy Inference trên GPU thông qua vLLM
    """
    if not llm:
        raise ValueError("vLLM Engine chưa được khởi tạo!")
    
    # vLLM xử lý Batch cực nhanh trên GPU
    outputs_list = llm.generate(batch_inputs, sampling_params=sampling_params)
    return outputs_list

# --- FALLBACK MECHANISM ---

class MockModelOutput:
    """Giả lập cấu trúc trả về của vLLM để đồng nhất dữ liệu đầu ra"""
    def __init__(self, text):
        # Tạo object giả lập để truy cập được dạng output.outputs[0].text
        self.outputs = [type('obj', (object,), {'text': text})]

def run_tesseract_fallback(images):
    """
    Cơ chế cứu hộ: Chạy Tesseract OCR (CPU) nếu vLLM/GPU gặp sự cố
    """
    print("🔄 [FALLBACK] Đang xử lý bằng Tesseract (CPU)...")
    final_outputs = []
    
    for idx, img in enumerate(images):
        try:
            # lang='vie+eng' để hỗ trợ song ngữ Việt - Anh
            # config='--psm 3' (Fully automatic page segmentation) thường cho kết quả tốt nhất
            text = pytesseract.image_to_string(img, lang='vie+eng', config='--psm 3')
            final_outputs.append(MockModelOutput(text))
        except Exception as e:
            print(f"⚠️ Lỗi Tesseract tại trang {idx + 1}: {e}")
            final_outputs.append(MockModelOutput(f"[Trang {idx+1} lỗi: {str(e)}]"))
            
    return final_outputs
import os
import io
import re
from tqdm import tqdm


import torch
from typing import Optional, Tuple


from concurrent.futures import ThreadPoolExecutor
 

from app.config import MODEL_PATH, INPUT_PATH, OUTPUT_PATH, PROMPT, SKIP_REPEAT, MAX_CONCURRENCY, NUM_WORKERS, CROP_MODE, OCR_DPI, IMAGE_ENHANCE_ENABLED

from PIL import Image, ImageDraw, ImageFont
import numpy as np

# NOTE: Removed DeepSeek-specific imports to avoid vLLM version conflicts
# from app.core.engine.deepseek_model import DeepseekOCRForCausalLM
# from vllm.model_executor.models.registry import ModelRegistry
# from vllm import LLM, SamplingParams
# from app.core.ngram_norepeat import NoRepeatNGramLogitsProcessor
# from app.core.image_process import DeepseekOCRProcessor

# NOTE: PDF-related imports moved to lazy loading (fitz, img2pdf)
# These are only imported in functions that actually use them


# =============================================================================
# IMAGE PREPROCESSING: DESKEW
# =============================================================================


def detect_and_correct_skew(pil_image):  
    """  
    Phát hiện và sửa ảnh bị nghiêng bằng Tesseract OSD  
      
    Args:  
        pil_image: PIL.Image object  
          
    Returns:  
        PIL.Image: Đã được sửa nếu cần  
    """  
    print(f"\n🔧 [DEBUG detect_and_correct_skew] CALLED!")
    print(f"   Input image size: {pil_image.size}, mode: {pil_image.mode}")
    
    # Kiểm tra tỷ lệ ảnh để phát hiện landscape
    width, height = pil_image.size
    aspect_ratio = width / height if height > 0 else 0
    is_landscape = width > height
    print(f"   Aspect ratio: {aspect_ratio:.2f} ({'LANDSCAPE' if is_landscape else 'PORTRAIT'})")
    
    try:  
        # Lazy import - chỉ import khi dùng
        import pytesseract
        import imutils
        from pytesseract import Output
        print(f"   ✅ pytesseract & imutils imported successfully")
        
        # Chuyển PIL sang numpy array cho OpenCV  
        image_array = np.array(pil_image)  
        print(f"   Image array shape: {image_array.shape}")
            
        # Phát hiện hướng văn bản ( OSD - Orientation and Script Detection)  
        print(f"   🔍 Running Tesseract OSD...")
        results = pytesseract.image_to_osd(image_array, output_type=Output.DICT)  
        print(f"   📊 OSD Results: {results}")
          
        # Lấy góc xoay cần thiết  
        rotation_angle = results.get("rotate", 0)
        orientation = results.get("orientation", 0)
        orientation_conf = results.get("orientation_conf", 0)
        script = results.get("script", "unknown")
        
        print(f"   Detected rotation: {rotation_angle}°")
        print(f"   Detected orientation: {orientation}")
        print(f"   Orientation confidence: {orientation_conf}")
        print(f"   Script: {script}")
          
        if rotation_angle != 0:  
            # Xoay ảnh về hướng đã sửa  
            print(f"   🔄 Rotating image by {rotation_angle}°...")
            rotated = imutils.rotate_bound(image_array, angle=rotation_angle)  
            result = Image.fromarray(rotated)
            print(f"   📐 Deskew: rotated {rotation_angle}° (Tesseract OSD)")
            print(f"   Output size: {result.size}")
            print(f"   ✅ [DEBUG detect_and_correct_skew] ROTATED")
            return result  
        else:  
            # Không cần xoay  
            print(f"   ⏭️  No rotation needed (angle=0)")
            print(f"   ✅ [DEBUG detect_and_correct_skew] NO CHANGE")
            return pil_image  
              
    except ImportError as ie:
        print(f"⚠️  Optional dependencies not available (pytesseract, imutils): {ie}")
        return pil_image
        
    except pytesseract.TesseractError as te:
        # Lỗi "Too few characters" là bình thường với trang ít chữ/ảnh
        if "Too few characters" in str(te):
            print(f"   ⚠️  [Deskew Skipped] Too few characters for OSD.")
        else:
            print(f"   ⚠️  TesseractError: {te}")
        return pil_image
        
    except Exception as e:      
        print(f"⚠️  Lỗi khi xử lý ảnh (OSD): {e}")  
        # import traceback
        # traceback.print_exc()
        return pil_image


def enhance_for_ocr(pil_image):
    """
    Tăng chất lượng ảnh cho OCR tiếng Việt.
    - CLAHE: tăng contrast cục bộ (làm rõ dấu mờ)
    - Unsharp mask: sharpen nét ký tự
    
    Returns: PIL Image đã enhance
    """
    try:
        import cv2
        img_array = np.array(pil_image)
        
        # Convert to LAB color space for CLAHE on luminance only
        if len(img_array.shape) == 3:
            lab = cv2.cvtColor(img_array, cv2.COLOR_RGB2LAB)
            l_channel, a_channel, b_channel = cv2.split(lab)
        else:
            l_channel = img_array
            a_channel = None
            b_channel = None
        
        # CLAHE - tăng contrast cục bộ (clip=1.5 nhẹ, tileSize=8x8)
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        enhanced_l = clahe.apply(l_channel)
        
        # Merge back
        if a_channel is not None:
            enhanced_lab = cv2.merge([enhanced_l, a_channel, b_channel])
            enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2RGB)
        else:
            enhanced = enhanced_l
        
        # Unsharp mask - sharpen (kernel=3, amount=0.5)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), 3)
        sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)
        
        result = Image.fromarray(sharpened)
        return result
        
    except Exception as e:
        print(f"⚠️  Image enhancement failed: {e}")
        return pil_image


def preprocess_image(image: Image.Image, deskew: bool = True, crop_pixels: int = 0) -> Tuple[Image.Image, dict]:
    """
    Pipeline tiền xử lý ảnh: deskew.
    
    Args:
        image: PIL Image input
        deskew: Có chỉnh nghiêng không
        crop_pixels: Deprecated (không dùng)
        
    Returns:
        Tuple (processed_image, preprocess_info)
        preprocess_info: dict chứa thông tin để tính toán ngược
    """
    print(f"\n" + "="*60)
    print(f"🔧 [DEBUG preprocess_image] PIPELINE START")
    print(f"   Input size: {image.size}, mode: {image.mode}")
    print(f"   deskew={deskew}")
    print(f"="*60)
    
    preprocess_info = {
        'deskew_applied': False,
        'enhance_applied': False,
        'deskew_angle': 0.0,
        'crop_applied': False,
        'crop_info': None,
        'original_size': image.size,
        'final_size': image.size
    }
    
    processed = image
    
    # 1. Deskew - Xoay ảnh nghiêng bằng Tesseract OSD
    if deskew:
        print(f"\n>>> STEP 1: DESKEW (enabled={deskew})")
        size_before = processed.size
        processed = detect_and_correct_skew(processed)
        size_after = processed.size
        preprocess_info['deskew_applied'] = True
        print(f"   Size change: {size_before} → {size_after}")
    else:
        print(f"\n>>> STEP 1: DESKEW SKIPPED (disabled)")
    
    # 2. Image enhancement - CLAHE + sharpen
    if IMAGE_ENHANCE_ENABLED:
        print(f"\n>>> STEP 2: IMAGE ENHANCEMENT (enabled)")
        processed = enhance_for_ocr(processed)
        preprocess_info['enhance_applied'] = True
        print(f"   ✅ Enhanced (CLAHE + sharpen)")
    else:
        print(f"\n>>> STEP 2: IMAGE ENHANCEMENT SKIPPED (disabled)")
    
    preprocess_info['final_size'] = processed.size
    
    print(f"\n" + "="*60)
    print(f"🔧 [DEBUG preprocess_image] PIPELINE END")
    print(f"   Original: {preprocess_info['original_size']}")
    print(f"   Final:    {preprocess_info['final_size']}")
    print(f"   Deskew applied: {preprocess_info['deskew_applied']}")
    print(f"   Crop applied: {preprocess_info['crop_applied']}")
    print(f"="*60 + "\n")
    
    return processed, preprocess_info


class Colors:
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    RESET = '\033[0m' 


def pdf_to_images_high_quality(pdf_path, dpi=None, image_format="PNG", start_page=0, end_page=None):
    # Use config DPI if not explicitly specified
    if dpi is None:
        dpi = OCR_DPI
    """Convert PDF pages to images"""
    # Lazy import - only when actually needed
    import fitz
    
    images = []
    pdf_document = fitz.open(pdf_path)
    total_pages = pdf_document.page_count
    
    # Giới hạn trang theo batch
    if end_page is None or end_page > total_pages:
        end_page = total_pages

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    
    # Chỉ render đoạn 20 trang
    for page_num in range(start_page, end_page):
        page = pdf_document[page_num]
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        Image.MAX_IMAGE_PIXELS = None

        # --- LOGIC GỐC CỦA CƯƠNG ---
        if image_format.upper() == "PNG":
            img_data = pixmap.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
        else:
            img_data = pixmap.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            if img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
        images.append(img)
    
    pdf_document.close()
    return images

def pil_to_pdf_img2pdf(pil_images, output_path):

    if not pil_images:
        return
    
    image_bytes_list = []
    
    for img in pil_images:
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='JPEG', quality=95)
        img_bytes = img_buffer.getvalue()
        image_bytes_list.append(img_bytes)
    
    try:
        pdf_bytes = img2pdf.convert(image_bytes_list)
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

    except Exception as e:
        print(f"error: {e}")

    
def get_gpu_info() -> Tuple[Optional[str], Optional[int]]:
    """
    Lấy thông tin GPU đang dùng.
    Return: (gpu_name, total_mb) hoặc (None, None) nếu không có CUDA.
    """
    if not torch.cuda.is_available():
        return None, None
    idx = torch.cuda.current_device()
    name = torch.cuda.get_device_name(idx)
    total_mb = int(torch.cuda.get_device_properties(idx).total_memory / (1024 * 1024))
    return name, total_mb
def reset_gpu_peak():
    """
    Reset peak memory stats để đo "peak VRAM" chính xác cho từng job.
    """
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
def read_gpu_peak_mb() -> Tuple[Optional[int], Optional[int]]:
    """
    Read peak memory used during job.
    - allocated: memory do tensors allocate
    - reserved : memory cached by CUDA allocator
    """
    if not torch.cuda.is_available():
        return None, None
    peak_alloc = int(torch.cuda.max_memory_allocated() / (1024 * 1024))
    peak_resv = int(torch.cuda.max_memory_reserved() / (1024 * 1024))
    return peak_alloc, peak_resv





def apply_regex_heuristics(text: str) -> str:
    if not text or not text.strip():
        return text
    
    date_pattern = r"(\d{1,2}/\d{1,2}/\d{4})"
    match = re.search(date_pattern, text)
    if match:
        start, end = match.span()
        prefix = text[:start].strip()
        date_val = match.group(1)
        suffix = text[end:].strip()
        
        parts = []
        if prefix: parts.append(prefix)
        parts.append(date_val)
        if suffix: parts.append(suffix)
        return " | ".join(parts)
    
    # Tách số dính chữ an toàn
    return re.sub(r'([a-zA-Z])(\d)', r'\1 | \2', text)

def validate_financial_rows(rows: list) -> str:
    try:
        data_values = []
        total_value = 0
        has_total_row = False

        for row in rows:
            # Join các cột, bỏ dấu phân cách
            row_str = " ".join(row).replace('.', '').replace(',', '')
            # Tìm tất cả số
            nums = re.findall(r'[-+]?\d+', row_str)
            
            # KIỂM TRA AN TOÀN: Nếu hàng không có số nào thì bỏ qua
            if not nums: 
                continue
            
            # Lấy số cuối cùng an toàn
            current_val = int(nums[-1])

            if any(kw in row_str.lower() for kw in ["cộng", "tổng cộng", "total"]):
                total_value = current_val
                has_total_row = True
            else:
                data_values.append(current_val)

        if has_total_row and data_values:
            calculated_sum = sum(data_values)
            if abs(calculated_sum - total_value) > 2:
                return "Low Confidence Table (Column Shift Detected)"
        
        return "High"
    except (ValueError, IndexError, Exception):
        # Trả về Indeterminate thay vì làm sập cả Job
        return "Indeterminate"
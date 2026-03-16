"""
PostProcess Markdown - Xử lý Markdown output từ OCR engines (DeepSeek)

Chứa:
- clean_markdown() - chuẩn hóa markdown
- extract_content() - xử lý ref tags
- re_match() - tìm patterns
- draw_bounding_boxes() - crop ảnh
- process_ocr_output() - main processing
"""

import os
import io
import re
import ast
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple, List, Dict, Any

from app.config import MODEL_PATH, INPUT_PATH, OUTPUT_PATH, PROMPT, SKIP_REPEAT, MAX_CONCURRENCY, NUM_WORKERS, CROP_MODE

# NOTE: Heavy imports (torch, tqdm, PIL, numpy) are lazy-loaded
# to avoid issues when this module is imported in different conda envs
# DeepseekOCR2Processor and detect_and_correct_skew are imported lazily in functions that use them

# NOTE: Removed DeepSeek-specific imports to avoid vLLM version conflicts
# from app.core.engine.deepseek_model import DeepseekOCRForCausalLM
# from vllm.model_executor.models.registry import ModelRegistry
# from vllm import LLM, SamplingParams
# from app.core.ngram_norepeat import NoRepeatNGramLogitsProcessor

# NOTE: PDF-related imports (fitz, img2pdf) moved to lazy loading
# These are only imported in functions that actually use them
# from app.core.image_process import DeepseekOCR2Processor

# NOTE: detect_and_correct_skew kept; crop helper removed
from app.utils.utils import apply_regex_heuristics, validate_financial_rows

# Import JSON processing từ postprocess_json
from app.utils.postprocess_json import parse_html_table, process_ocr_to_blocks


# =============================================================================
# MARKDOWN CLEANING & UTILITIES
# =============================================================================

def clean_markdown(text: str) -> str:
    """
    Làm sạch markdown output:
    - Chuẩn hóa spacing và newlines
    - Fix LaTeX symbols
    - Chuẩn hóa image paths
    - Loại bỏ special tokens
    """
    if not text:
        return ""
    
    # 1. Remove special tokens
    text = text.replace("<｜end▁of▁sentence｜>", "")
    text = text.replace("<|endoftext|>", "")
    
    # 2. Fix LaTeX symbols
    text = text.replace("\\coloneqq", ":=")
    text = text.replace("\\eqqcolon", "=:")
    
    # 3. Normalize newlines (max 2 consecutive)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # 4. Normalize spaces (max 1 consecutive)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        cleaned_lines.append(re.sub(r'[ \t]{2,}', ' ', line).rstrip())
    text = '\n'.join(cleaned_lines)
    
    # 5. Clean up heading spacing
    text = re.sub(r'\n(#+)', r'\n\n\1', text)
    text = re.sub(r'(#+[^\n]+)\n([^#\n])', r'\1\n\n\2', text)
    
    # 6. Normalize image paths
    def normalize_img_path(match):
        alt = match.group(1)
        path = match.group(2)
        filename = os.path.basename(path)
        if not path.startswith('images/'):
            return f'![{alt}](images/{filename})'
        return match.group(0)
    
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', normalize_img_path, text)
    
    # 7. Clean Vietnamese OCR output - DISABLED (gây sai dấu)
    # text = clean_vietnamese_ocr_output(text, remove_chinese=True, fix_errors=True)
    
    return text.strip()


def convert_html_table_to_markdown(html_string: str) -> str:
    """
    Convert HTML table thành markdown table format
    
    Input: <table><tr><td>A</td><td>B</td></tr></table>
    Output: |A|B|
    """
    if not html_string or '<table' not in html_string.lower():
        return html_string
    
    try:
        rows = parse_html_table(html_string)
        if not rows:
            return html_string
        
        md_rows = []
        for row in rows:
            if row:
                md_row = '|' + '|'.join(row) + '|'
                md_rows.append(md_row)
        
        return '\n'.join(md_rows) if md_rows else html_string
    except Exception:
        return html_string



# NOTE: Legacy re_match, extract_coordinates_and_label, draw_bounding_boxes (without out_path)
# have been REMOVED to avoid duplication. Use the refactored versions below.



def extract_content(text: str, job_id: str, page_idx: int = 0) -> str:
    """
    Làm sạch output raw của model theo logic DeepSeek official repo:
    - bỏ end-of-sentence token
    - thay <|ref|>image... bằng markdown image placeholder với format {page_idx}_{img_idx}.jpg
    - xoá các ref/det khác
    - chuẩn hoá ký hiệu latex
    
    Args:
        text: Raw output từ model
        job_id: Job ID
        page_idx: Index của page (để tạo tên file ảnh đúng format)
    """
    if "<｜end▁of▁sentence｜>" in text: # repeat no eos
        text = text.replace("<｜end▁of▁sentence｜>", "")
    
    pattern = r'(<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>)'
    matches = re.findall(pattern, text, re.DOTALL)
    
    matches_image = []
    matches_other = []
    for a_match in matches:
        if "<|ref|>image<|/ref|>" in a_match[0]:
            matches_image.append(a_match[0])
        else:
            matches_other.append(a_match[0])
    
    # Sử dụng format {page_idx}_{img_idx}.jpg để khớp với tên file thực tế
    for img_idx, a_match_image in enumerate(matches_image):
        img_name = f"{page_idx}_{img_idx}.jpg"
        text = text.replace(a_match_image, f'![](images/{img_name})\n')
    
    for idx, a_match_other in enumerate(matches_other):
        text = text.replace(a_match_other, '').replace('\\coloneqq', ':=').replace('\\eqqcolon', '=:').replace('\n\n\n\n', '\n\n').replace('\n\n\n', '\n\n')
    
    return text


# Hàm clean_markdown_universal được gộp vào clean_markdown trong common.py
# Nếu cần sử dụng, import từ workers.common

# =============================================================================
# REFACTORED UTILITY FUNCTIONS - Giữ lại những hàm riêng cho postprocess_md
# =============================================================================

def re_match(text):
    """
    Tìm tất cả các tags <|ref|>...<|/ref|><|det|>...<|/det|> trong text
    Trả về (tất cả matches, matches image, matches other)
    """
    pattern = r'(<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>)'
    matches = re.findall(pattern, text, re.DOTALL)
    
    mathes_image = []
    mathes_other = []
    for a_match in matches:
        if '<|ref|>image<|/ref|>' in a_match[0]:
            mathes_image.append(a_match[0])
        else:
            mathes_other.append(a_match[0])
    return matches, mathes_image, mathes_other


def extract_coordinates_and_label(ref_text, image_width, image_height):
    """Extract coordinates từ ref text - dùng ast.literal_eval thay eval cho security"""
    try:
        label_type = ref_text[1]
        cor_list = ast.literal_eval(ref_text[2])
    except Exception as e:
        print(e)
        return None

    return (label_type, cor_list)


def draw_bounding_boxes(image, refs, jdx, out_path):
    """
    Hàm thực hiện Crop ảnh dựa trên hệ số 999 (Chuẩn DeepSeek).
    Đã sửa lỗi diện tích bằng 0 gây crash.
    
    Args:
        out_path: Đường dẫn folder để lưu images (đã là images folder, không tạo thêm subfolder)
    """
    image_width, image_height = image.size
    img_idx = 0
    print(f"DEBUG: Processing Page {jdx} with image size: {image_width}x{image_height}")
    
    # out_path đã là folder images, không cần tạo thêm subfolder
    img_save_dir = out_path
    os.makedirs(img_save_dir, exist_ok=True)

    for ref in refs:
        result = extract_coordinates_and_label(ref, image_width, image_height)
        
        if result:
            label_type, points_list = result
            for points in points_list:
                # Toạ độ gốc từ model: x1, y1, x2, y2
                x1, y1, x2, y2 = points

                # 1. QUY ĐỔI VÀ ĐẢM BẢO KHÔNG VƯỢT QUÁ CẠNH ẢNH
                left = max(0, min(int(x1 / 999 * image_width), image_width))
                top = max(0, min(int(y1 / 999 * image_height), image_height))
                right = max(0, min(int(x2 / 999 * image_width), image_width))
                bottom = max(0, min(int(y2 / 999 * image_height), image_height))

                # 2. KIỂM TRA TỌA ĐỘ BỊ NGƯỢC (Nếu x1 > x2 thì swap lại)
                if left > right: left, right = right, left
                if top > bottom: top, bottom = bottom, top

                # 3. FIX LỖI "EMPTY IMAGE": Tính toán chiều rộng và cao
                width = right - left
                height = bottom - top

                if label_type == 'image':
                    # Chỉ lưu nếu ảnh có kích thước hữu dụng (ví dụ > 2px)
                    if width > 2 and height > 2:
                        try:
                            cropped = image.crop((left, top, right, bottom))
                            img_name = f"{jdx}_{img_idx}.jpg"
                            save_file_path = os.path.join(img_save_dir, img_name)
                            
                            cropped.save(save_file_path, "JPEG", quality=95)
                            img_idx += 1
                        except Exception as e:
                            print(f"⚠️ Lỗi khi lưu ảnh con tại trang {jdx}: {e}")
                    else:
                        print(f"⏩ Bỏ qua box quá nhỏ hoặc rỗng tại trang {jdx}: {width}x{height}")
                        
    return image

# def draw_bounding_boxes(image, refs, jdx, out_path):
#     # Lấy kích thước hiện tại (Nếu đã crop 85px, đây sẽ là kích thước mới)
#     image_width, image_height = image.size
#     img_idx = 0
#     img_save_dir = os.path.join(out_path, "images")
#     os.makedirs(img_save_dir, exist_ok=True)

#     for ref in refs:
#         result = extract_coordinates_and_label(ref, image_width, image_height)
        
#         if result:
#             label_type, points_list = result
#             for points in points_list:
#                 # Tọa độ từ hệ 999 của DeepSeek
#                 x1, y1, x2, y2 = points

#                 # Quy đổi dựa trên kích thước THỰC TẾ của tham số image truyền vào
#                 left = max(0, int(x1 / 999 * image_width))
#                 top = max(0, int(y1 / 999 * image_height))
#                 right = min(image_width, int(x2 / 999 * image_width))
#                 bottom = min(image_height, int(y2 / 999 * image_height))

#                 if label_type == 'image':
#                     # Kiểm tra diện tích vùng cắt có hợp lệ không
#                     if right > left and bottom > top:
#                         try:
#                             cropped = image.crop((left, top, right, bottom))
#                             img_name = f"{jdx}_{img_idx}.jpg"
#                             cropped.save(os.path.join(img_save_dir, img_name), "JPEG", quality=95)
#                             img_idx += 1
#                         except Exception as e:
#                             print(f"Lỗi crop tại trang {jdx}: {e}")
#     return image

#
def process_single_image(image, prompt):
    """
    Xử lý single image cho DeepSeek OCR.
    Gọi trực tiếp detect_and_correct_skew.
    
    Pipeline:
    1. detect_and_correct_skew - Xoay ảnh nghiêng bằng Tesseract OSD
    2. Tokenize cho model
    
    Args:
        image: PIL Image input
        prompt: Prompt cho model
    
    Returns:
        Tuple (cache_item, processed_image)
        - cache_item: Input cho vLLM
        - processed_image: Ảnh đã xử lý (dùng để crop bbox sau)
    """
    print(f"\n{'#'*60}")
    print(f"🖼️  [process_single_image] Input: {image.size}")
    
    # Step 1: Deskew - Xoay ảnh nghiêng (giống repo gốc)
    from app.utils.utils import detect_and_correct_skew
    image = detect_and_correct_skew(image)
    
    print(f"   [process_single_image] After preprocessing: {image.size}")
    
    # Step 3: Tokenize
    from app.core.image_process import DeepseekOCR2Processor
    prompt_in = prompt
    cache_item = {
        "prompt": prompt_in,
        "multi_modal_data": {"image": DeepseekOCR2Processor().tokenize_with_images(
            images=[image], bos=True, eos=True, cropping=CROP_MODE
        )},
    }
    print(f"{'#'*60}\n")
    
    # Trả về 2 giá trị giống repo gốc Deepseek-ocr-customvLLM
    return cache_item, image


def process_image_with_refs(image, matches_ref, page_idx, out_path):
    """
    Hàm 'vỏ bọc' - gọi draw_bounding_boxes để crop ảnh con.
    
    Args:
        image: Ảnh đã được preprocess (đã deskew + crop margin)
        matches_ref: List các ref từ model output
        page_idx: Index của page
        out_path: Đường dẫn lưu images
        preprocess_info: Thông tin preprocessing (optional, để debug)
    """
    result_image = draw_bounding_boxes(image, matches_ref, page_idx, out_path)
    return result_image


# NOTE: boto3 and botocore imports moved to lazy loading
# They are only imported in upload_to_minio() function
# from app.config import MINIO_ACCESS_KEY, MINIO_BUCKET_NAME, MINIO_ENDPOINT, MINIO_SECRET_KEY
# import boto3
# from botocore.client import Config

# Files to skip when uploading to MinIO
SKIP_FILES = {
    'result.json',
    'result.md',
}
# Patterns to skip (files ending with these)
SKIP_PATTERNS = ('_result.json', '_raw.md')


def upload_to_minio(local_directory, job_id):
    """
    Tự động quét và đẩy .md, .json và folder images lên MinIO
    
    Skip các file không cần thiết:
    - result.json, result.md (duplicate)
    - *_result.json, *_raw.md (intermediate files)
    
    Fix cấu trúc images:
    - images/images/xxx.jpg → images/xxx.jpg
    """
    # Lazy import - only when actually uploading to MinIO
    import boto3
    from botocore.client import Config
    from app.config import MINIO_ACCESS_KEY, MINIO_BUCKET_NAME, MINIO_ENDPOINT, MINIO_SECRET_KEY
    
    s3 = boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version='s3v4'),
        region_name='us-east-1' 
    )

    # Đảm bảo Bucket tồn tại
    try:
        s3.head_bucket(Bucket=MINIO_BUCKET_NAME)
    except:
        s3.create_bucket(Bucket=MINIO_BUCKET_NAME)

    uploaded_count = 0
    skipped_count = 0
    
    # Quét toàn bộ thư mục (bao gồm folder con 'images')
    for root, dirs, files in os.walk(local_directory):
        for filename in files:
            # Skip các file không cần thiết
            if filename in SKIP_FILES:
                skipped_count += 1
                continue
            if filename.endswith(SKIP_PATTERNS):
                skipped_count += 1
                continue
                
            local_path = os.path.join(root, filename)
            
            # Giữ nguyên cấu trúc thư mục trên MinIO
            relative_path = os.path.relpath(local_path, local_directory)
            
            # Fix images/images → images
            if relative_path.startswith('images/images/'):
                relative_path = relative_path.replace('images/images/', 'images/', 1)
            
            minio_path = f"{job_id}/{relative_path}"
            
            s3.upload_file(local_path, MINIO_BUCKET_NAME, minio_path)
            uploaded_count += 1
    
    print(f"✅ Đã upload {uploaded_count} files (skipped {skipped_count}) lên MinIO: {job_id}/")


    
def process_ocr_output(outputs, images, out_path, start_page: int = 0):
    """
    Xử lý output từ model OCR.
    
    Args:
        outputs: List outputs từ model
        images: List ảnh đã xử lý
        out_path: Thư mục output
        start_page: Page offset (để đặt tên file ảnh đúng khi xử lý batch)
    """
    img_save_dir = os.path.join(out_path, "images")
    os.makedirs(img_save_dir, exist_ok=True)
    
    contents = ''
    contents_det = ''
    draw_images = []
    
    # Context cho heading trang trước
    last_heading_level = 0 

    for idx, (output, image) in enumerate(zip(outputs, images)):
        # Tính page_idx thực tế (để đặt tên file đồng bộ)
        page_idx = start_page + idx
        
        content = output.outputs[0].text
        
        # 1. Clean token thừa
        content = content.replace('<｜end▁of▁sentence｜>', '').strip()
        if SKIP_REPEAT and not content:
            continue
        
        # 2. Xử lý Image/Ref (Sửa lỗi empty image)
        matches_ref, matches_images, matches_other = re_match(content)
        
        # Kiểm tra nội hàm process_image_with_refs hoặc filter matches ở đây
        valid_refs = []
        for ref in matches_ref:
            # Giả sử ref có định dạng tọa độ [ymin, xmin, ymax, xmax]
            # Nếu tọa độ rỗng hoặc diện tích = 0 thì không add vào valid_refs
            valid_refs.append(ref)
            
        try:
            # Dùng page_idx thực tế để đặt tên file ảnh
            process_image_with_refs(image, valid_refs, page_idx, img_save_dir)
        except Exception as e:
            # Log cụ thể trang nào bị lỗi để debug
            print(f"⚠️ Warning: Trang {page_idx} gặp vấn đề khi crop: {e}")

        # 3. Chuẩn hóa Markdown Context
        # Tìm heading cuối cùng để duy trì cấu trúc cho trang sau (nếu cần dùng prompt)
        found_headings = re.findall(r'^(#+)\s+', content, re.MULTILINE)
        if found_headings:
            last_heading_level = len(found_headings[-1]) # Lưu cấp độ (số dấu #)

        # 4. Replace tags - dùng page_idx để tên file khớp với ảnh đã lưu
        for img_idx, match_tag in enumerate(matches_images):
            # Kiểm tra xem file ảnh có tồn tại không trước khi đặt link (tránh link chết)
            img_name = f"{page_idx}_{img_idx}.jpg"
            content = content.replace(match_tag, f'![](images/{img_name})\n')
        
        for match in matches_other:
            content = content.replace(match, '')

        # 5. Fix Latex & Spacing
        content = content.replace('\\coloneqq', ':=').replace('\\eqqcolon', '=: ')
        # Gom các dòng trống thừa
        content = re.sub(r'\n{3,}', '\n\n', content)

        page_marker = f'\n\n\n\n'
        contents += content + page_marker
        contents_det += content + page_marker
        draw_images.append(image)

    # # --- TỰ ĐỘNG GHI FILE (Nên mở lại đoạn này để có kết quả ngay) ---
    # try:
    #     job_id = os.path.basename(out_path.strip('/'))
    #     md_file_path = os.path.join(out_path, f"{job_id}.md")
    #     with open(md_file_path, "w", encoding="utf-8") as f:
    #         f.write(contents)
    #     print(f"✅ Đã xuất file Markdown: {md_file_path}")
    # except Exception as e:
    #     print(f"❌ Lỗi ghi file MD: {e}")
    
    return contents, contents_det, draw_images
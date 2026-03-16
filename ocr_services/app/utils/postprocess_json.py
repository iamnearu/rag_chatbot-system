"""
PostProcess JSON - Xử lý JSON output từ OCR engines

Chứa:
- parse_html_table() - phân tích HTML tables
- process_ocr_to_blocks() - chuyển markdown thành block structure
- process_pages_to_document() - xử lý multiple pages
- process_single_markdown_to_document() - xử lý single markdown
- assign_captions_to_images() - gán caption cho images từ paragraph phía sau
- extract_caption_from_html() - trích xuất caption từ HTML tags
"""

import re
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

from app.utils.utils import apply_regex_heuristics, validate_financial_rows


# =============================================================================
# TEXT PREPROCESSING UTILITIES
# =============================================================================

def extract_caption_from_html(text: str) -> Tuple[bool, str]:
    """
    Trích xuất caption từ HTML tags như <center>, <figcaption>, etc.
    
    Returns:
        Tuple (is_caption, cleaned_text)
        - is_caption: True nếu text chứa caption pattern
        - cleaned_text: Text đã loại bỏ HTML tags
    """
    if not text:
        return False, ""
    
    # Patterns HTML chứa caption
    html_caption_patterns = [
        r'<center>\s*(.*?)\s*</center>',
        r'<figcaption>\s*(.*?)\s*</figcaption>',
        r'<caption>\s*(.*?)\s*</caption>',
    ]
    
    for pattern in html_caption_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            inner_text = match.group(1).strip()
            # Kiểm tra inner text có phải caption không
            if is_image_caption(inner_text):
                return True, inner_text
    
    return False, text


def is_image_caption(text: str) -> bool:
    """
    Kiểm tra xem text có phải là caption của hình ảnh không.
    
    Patterns nhận dạng caption:
    - Hình 1, Hình 1.1, Hình 1:, Hình 1.
    - Figure 1, Fig. 1, Fig 1
    - Sơ đồ 1, Biểu đồ 1
    - Ảnh 1, Picture 1
    - Minh họa 1
    - Caption trong <center> tag
    """
    if not text:
        return False
    
    # Loại bỏ HTML tags để check
    clean_text = re.sub(r'<[^>]+>', '', text).strip()
    text_lower = clean_text.lower()
    
    # Patterns cho caption (bắt đầu dòng)
    caption_patterns = [
        r'^hình\s*\d+',           # Hình 1, Hình 1.1
        r'^h[ìi]nh\s+\d+',        # Hình với dấu
        r'^figure\s*\d+',         # Figure 1
        r'^fig\.?\s*\d+',         # Fig. 1, Fig 1
        r'^sơ\s*đồ\s*\d+',        # Sơ đồ 1
        r'^biểu\s*đồ\s*\d+',      # Biểu đồ 1
        r'^ảnh\s*\d+',            # Ảnh 1
        r'^picture\s*\d+',        # Picture 1
        r'^minh\s*họa\s*\d+',     # Minh họa 1
        r'^bảng\s*\d+',           # Bảng 1 (có thể là caption cho hình chứa bảng)
        r'^table\s*\d+',          # Table 1
        r'^chart\s*\d+',          # Chart 1
        r'^diagram\s*\d+',        # Diagram 1
        r'^phụ\s*lục\s*\d+',      # Phụ lục 1
        r'^appendix\s*\d+',       # Appendix 1
        r'^biêu\s*đ[ôồổỗộ]',      # Biêu đồ (OCR error variant)
        r'^h[iì]nh\s*thực',       # Hình thực (variant)
    ]
    
    for pattern in caption_patterns:
        if re.match(pattern, text_lower, re.IGNORECASE):
            return True
    
    # Check if wrapped in HTML caption tags
    if re.search(r'<center>.*?(hình|figure|sơ đồ|biểu đồ|bảng|table)\s*\d+', text, re.IGNORECASE):
        return True
    
    return False


def clean_caption_text(text: str) -> str:
    """
    Làm sạch text caption - loại bỏ HTML tags, normalize whitespace.
    """
    if not text:
        return ""
    
    # Loại bỏ các HTML tags phổ biến
    text = re.sub(r'</?center>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?figcaption>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?caption>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?[a-z]+[^>]*>', '', text, flags=re.IGNORECASE)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def assign_captions_to_images(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Quét qua list blocks và gán caption cho images từ paragraph ngay sau hoặc trước nó.
    
    Logic:
    1. Tìm block type="image"
    2. Kiểm tra block ngay SAU (ưu tiên) - nếu là paragraph và match caption pattern
    3. Nếu không có, kiểm tra block ngay TRƯỚC
    4. Cũng check caption trong HTML tags (<center>Hình X</center>)
    5. Di chuyển text đó vào mảng caption của image
    6. Xóa block paragraph đã được gán làm caption
    
    Returns:
        List blocks đã được xử lý (có thể ngắn hơn do xóa caption paragraphs)
    """
    if not blocks:
        return blocks
    
    # Đánh dấu các index cần xóa
    indices_to_remove = set()
    
    # Pass 1: Gán caption từ paragraph ngay SAU image
    for i in range(len(blocks)):
        if blocks[i].get("type") == "image":
            # Kiểm tra block tiếp theo
            if i + 1 < len(blocks):
                next_block = blocks[i + 1]
                
                if next_block.get("type") == "paragraph":
                    next_text = next_block.get("text", "")
                    
                    # Check trực tiếp hoặc trong HTML tags
                    is_caption, clean_text = extract_caption_from_html(next_text)
                    if is_caption or is_image_caption(next_text):
                        # Gán vào caption của image
                        if not blocks[i].get("caption"):
                            blocks[i]["caption"] = []
                        # Clean HTML tags trước khi gán
                        caption_text = clean_caption_text(next_text)
                        blocks[i]["caption"].append(caption_text)
                        indices_to_remove.add(i + 1)
    
    # Pass 2: Gán caption từ paragraph ngay TRƯỚC image (nếu chưa có caption)
    for i in range(len(blocks)):
        if blocks[i].get("type") == "image":
            # Nếu chưa có caption và block trước đó chưa bị xóa
            if not blocks[i].get("caption") and i - 1 >= 0 and (i - 1) not in indices_to_remove:
                prev_block = blocks[i - 1]
                
                if prev_block.get("type") == "paragraph":
                    prev_text = prev_block.get("text", "")
                    
                    # Check trực tiếp hoặc trong HTML tags
                    is_caption, clean_text = extract_caption_from_html(prev_text)
                    if is_caption or is_image_caption(prev_text):
                        # Gán vào caption của image
                        caption_text = clean_caption_text(prev_text)
                        blocks[i]["caption"] = [caption_text]
                        indices_to_remove.add(i - 1)
    
    # Pass 3: Check heading ngay TRƯỚC có phải là caption dạng "BIỂU ĐỒ PARETO..."
    for i in range(len(blocks)):
        if blocks[i].get("type") == "image":
            if not blocks[i].get("caption") and i - 1 >= 0 and (i - 1) not in indices_to_remove:
                prev_block = blocks[i - 1]
                
                if prev_block.get("type") == "heading":
                    prev_text = prev_block.get("text", "")
                    # Check if heading is actually a caption
                    if re.match(r'^(BIỂU\s*ĐỒ|SƠ\s*ĐỒ|HÌNH|BẢNG)\s+', prev_text, re.IGNORECASE):
                        blocks[i]["caption"] = [prev_text]
                        # Convert heading to be removed
                        indices_to_remove.add(i - 1)
    
    # Tạo list mới loại bỏ các blocks đã được gán làm caption
    result = [block for i, block in enumerate(blocks) if i not in indices_to_remove]
    
    return result


# =============================================================================
# HTML TABLE PARSING
# =============================================================================

def parse_html_table(html_string: str) -> List[List[str]]:
    """
    Phân tích HTML Table thành List[List[str]]
    <table><tr><td>A</td><td>B</td></tr>...</table> -> [["A", "B"], ...]
    """
    rows = []
    row_matches = re.findall(r'<tr.*?>(.*?)</tr>', html_string, re.IGNORECASE | re.DOTALL)
    
    for row_content in row_matches:
        cell_matches = re.findall(r'<td.*?>(.*?)</td>', row_content, re.IGNORECASE | re.DOTALL)
        cleaned_cells = [cell.strip() for cell in cell_matches]
        if cleaned_cells:
            rows.append(cleaned_cells)
        
    return rows


# =============================================================================
# OCR TO BLOCKS PROCESSING (Schema từ b.py)
# =============================================================================

def process_ocr_to_blocks(markdown_text: str, page_idx: int = 0) -> List[Dict[str, Any]]:
    """
    Parse markdown text thành blocks theo schema chuẩn MỚI
    
    Block types:
    - {"type": "paragraph", "text": "...", "page_idx": N}
    - {"type": "heading", "level": 1, "text": "...", "page_idx": N}
    - {"type": "image", "img_path": "...", "caption": ["..."], "footnote": ["..."], "page_idx": N}
    - {"type": "table", "table_body": "| A | B |\\n|---|---|\\n| 1 | 2 |", "table_caption": ["..."], "table_footnote": ["..."], "page_idx": N}
    
    Features:
    - Tự động tách mục lục bị nối dính (split_toc_entries)
    - Tự động gán caption cho images từ paragraph phía sau (assign_captions_to_images)
    
    Args:
        markdown_text: Nội dung markdown
        page_idx: Index của page (để add page_idx vào mỗi block)
        
    Returns:
        List of blocks với schema mới
    """
    blocks = []
    lines = markdown_text.strip().split('\n')
    
    in_markdown_table = False
    current_markdown_lines = []
    current_paragraph = ""
    current_caption_lines = []
    current_footnote_lines = []
    
    def finalize_paragraph():
        nonlocal current_paragraph
        if current_paragraph.strip():
            raw_text = current_paragraph.strip()
            processed_text = apply_regex_heuristics(raw_text)
            blocks.append({
                "type": "paragraph", 
                "text": processed_text,
                "page_idx": page_idx
            })
            current_paragraph = ""
    
    def convert_html_table_to_markdown_body(html_string: str) -> str:
        """Convert HTML table thành markdown table body"""
        rows = parse_html_table(html_string)
        if not rows:
            return ""
        
        md_lines = []
        # Header row
        md_lines.append("| " + " | ".join(rows[0]) + " |")
        # Separator
        md_lines.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
        # Data rows
        for row in rows[1:]:
            # Pad row nếu thiếu cells
            while len(row) < len(rows[0]):
                row.append("")
            md_lines.append("| " + " | ".join(row) + " |")
        
        return "\n".join(md_lines)
            
    def finalize_markdown_table():
        nonlocal in_markdown_table, current_markdown_lines, current_caption_lines, current_footnote_lines
        if current_markdown_lines:
            try:
                # Giữ nguyên markdown table lines, chỉ clean up
                table_body = "\n".join(current_markdown_lines)
                
                blocks.append({
                    "type": "table",
                    "table_body": table_body,
                    "table_caption": current_caption_lines if current_caption_lines else [],
                    "table_footnote": current_footnote_lines if current_footnote_lines else [],
                    "page_idx": page_idx
                })
                current_caption_lines = []
                current_footnote_lines = []
            except Exception:
                blocks.append({
                    "type": "paragraph", 
                    "text": "\n".join(current_markdown_lines),
                    "page_idx": page_idx
                })
        in_markdown_table = False
        current_markdown_lines = []
    
    for line in lines:
        line_stripped = line.strip()
        
        # 1. Heading
        heading_match = re.match(r'^(#+)\s*(.*)', line_stripped)
        if heading_match:
            finalize_markdown_table()
            finalize_paragraph()
            blocks.append({
                "type": "heading", 
                "level": len(heading_match.group(1)), 
                "text": heading_match.group(2).strip(),
                "page_idx": page_idx
            })
            continue
            
        # 2. HTML Table - convert to markdown format
        if re.search(r'<table', line_stripped, re.IGNORECASE):
            finalize_markdown_table()
            finalize_paragraph()
            try:
                # Convert HTML table to markdown body
                table_body = convert_html_table_to_markdown_body(line_stripped)
                if table_body:
                    blocks.append({
                        "type": "table", 
                        "table_body": table_body,
                        "table_caption": current_caption_lines if current_caption_lines else [],
                        "table_footnote": current_footnote_lines if current_footnote_lines else [],
                        "page_idx": page_idx
                    })
                    current_caption_lines = []
                    current_footnote_lines = []
                else:
                    current_paragraph = line_stripped
                    finalize_paragraph()
            except Exception:
                current_paragraph = line_stripped
                finalize_paragraph()
            continue

        # 3. Markdown Table (starts with |)
        if line_stripped.startswith('|'):
            if not in_markdown_table:
                finalize_paragraph()
                in_markdown_table = True
            current_markdown_lines.append(line_stripped)
            continue
        
        # Empty line after markdown table
        if in_markdown_table and not line_stripped:
            finalize_markdown_table()
            continue
            
        # 4. Empty line
        if not line_stripped:
            if current_paragraph:
                finalize_paragraph()
            continue
            
        # 5. Image (![alt](path)) - xử lý caption/footnote
        image_match = re.match(r'^!\[([^\]]*)\]\((.*?)\)', line_stripped)
        if image_match:
            finalize_markdown_table()
            finalize_paragraph()
            img_path = image_match.group(2).strip()
            # Normalize image path: chỉ giữ filename, sẽ được update với full path sau
            if img_path:
                # Remove leading ./ hoặc directory prefix, chỉ lấy filename
                img_path = img_path.lstrip('./')  # Remove ./
                # Lấy filename từ path
                img_filename = os.path.basename(img_path)
                # Giữ tạm images/filename, sẽ được update với document_id sau
                img_path = f"images/{img_filename}"
            blocks.append({
                "type": "image", 
                "img_path": img_path,
                "caption": current_caption_lines if current_caption_lines else [],
                "footnote": current_footnote_lines if current_footnote_lines else [],
                "page_idx": page_idx
            })
            current_caption_lines = []
            current_footnote_lines = []
            continue
        
        # 6. Caption detection - để assign_captions_to_images xử lý sau
        # Tạo paragraph riêng cho caption để dễ gán sau
        if is_image_caption(line_stripped):
            finalize_paragraph()  # Finalize paragraph trước đó nếu có
            blocks.append({
                "type": "paragraph",
                "text": line_stripped,
                "page_idx": page_idx
            })
            continue
        
        # 7. Footnote detection (^, *, †, etc)
        footnote_match = re.match(r'^[\^*†‡§¶]+\s*(.*)', line_stripped)
        if footnote_match:
            current_footnote_lines.append(line_stripped)
            continue

        # 8. Regular text -> paragraph
        if not in_markdown_table:
            current_paragraph = (current_paragraph + " " + line_stripped) if current_paragraph else line_stripped
        else:
            finalize_markdown_table()
            current_paragraph = line_stripped
            
    # Finalize remaining
    finalize_markdown_table()
    finalize_paragraph()
    
    # Post-processing: Gán caption cho images từ paragraph ngay sau nó
    blocks = assign_captions_to_images(blocks)
    
    return blocks


def process_pages_to_document(
    pages_markdown: List[str],
    engine: str,
    job_id: str,
    file_name: str = "",
    images_base_path: str = ""
) -> Dict[str, Any]:
    """
    Process multiple pages markdown thành document structure hoàn chỉnh theo schema mới
    
    Args:
        pages_markdown: List of markdown strings, mỗi phần tử là 1 page
        engine: Tên engine (deepseek, mineru, docling)
        job_id: Job ID / Document ID
        file_name: Tên file gốc
        images_base_path: Base path cho images (không dùng nữa, tự động tạo từ job_id)
        
    Returns:
        Document dict theo schema mới
    """
    all_blocks = []
    
    # Tự động tạo base path từ job_id: ocr-results/{job_id}/images/
    auto_base_path = f"ocr-results/{job_id}/images/"
    
    for page_num, page_md in enumerate(pages_markdown, start=0):
        if not page_md or not page_md.strip():
            continue
            
        blocks = process_ocr_to_blocks(page_md, page_idx=page_num)
        
        # Update image paths với format mới: ocr-results/{job_id}/images/filename
        for block in blocks:
            if block.get("type") == "image" and "img_path" in block:
                img_path = block["img_path"]
                # Lấy filename từ path hiện tại
                filename = os.path.basename(img_path)
                # Tạo path mới với format: ocr-results/{job_id}/images/filename
                block["img_path"] = f"{auto_base_path}{filename}"
        
        all_blocks.extend(blocks)
    
    return {
        "document_id": job_id,
        "file_name": file_name,
        "total_pages": len(pages_markdown),
        "content": all_blocks
    }


def process_single_markdown_to_document(
    markdown_text: str,
    engine: str,
    job_id: str,
    file_name: str = "",
    images_base_path: str = ""
) -> Dict[str, Any]:
    """
    Process single markdown (không chia page) thành document structure theo schema mới
    
    Sử dụng page markers (--- hoặc \\newpage) để chia pages nếu có
    """
    # Try to split by page markers
    page_markers = [
        r'\n---\s*\n',  # Horizontal rule
        r'\\newpage',   # LaTeX newpage
        r'<--- page split --->',  # Custom marker
        r'---page---',  # Custom marker
    ]
    
    pages = [markdown_text]
    for marker in page_markers:
        if re.search(marker, markdown_text, re.IGNORECASE):
            pages = re.split(marker, markdown_text, flags=re.IGNORECASE)
            break
    
    # Filter empty pages
    pages = [p.strip() for p in pages if p.strip()]
    
    if not pages:
        pages = [markdown_text]
    
    return process_pages_to_document(pages, engine, job_id, file_name, images_base_path)


# =============================================================================
# BUILD DOCUMENT STRUCTURE (Dùng chung cho tất cả engines)
# =============================================================================

def build_document_structure(
    blocks: List[Dict[str, Any]],
    engine: str,
    job_id: str,
    file_name: str = "",
    total_pages: int = 1,
    images_base_path: str = ""
) -> Dict[str, Any]:
    """
    Build document structure theo schema chuẩn MỚI từ list blocks.
    Dùng chung cho DeepSeek, MinerU, Docling.
    
    Output schema:
    {
        "document_id": "uuid",
        "file_name": "document.pdf",
        "total_pages": 10,
        "content": [
            {
                "type": "heading",
                "text": "...",
                "level": 1,
                "page_idx": 0
            },
            {
                "type": "paragraph",
                "text": "...",
                "page_idx": 0
            },
            {
                "type": "image",
                "img_path": "ocr-results/{job_id}/images/img_001.png",
                "caption": ["Hình 1: Biểu đồ"],
                "footnote": ["* Dữ liệu từ 2024"],
                "page_idx": 0
            },
            {
                "type": "table",
                "table_body": "| Col1 | Col2 |\\n|------|------|\\n|A|B|",
                "html": null or "<table>...</table>",
                "table_caption": ["Bảng 1: Dữ liệu"],
                "table_footnote": ["† Nguồn: Dự liệu gốc"],
                "page_idx": 0
            }
        ]
    }
    
    Args:
        blocks: List of blocks từ process_ocr_to_blocks()
        engine: Tên engine ("DeepSeek", "MinerU", "Docling")
        job_id: Job ID / Document ID
        file_name: Tên file gốc
        total_pages: Số trang
        images_base_path: Base path cho images (không dùng nữa, tự động tạo từ job_id)
        
    Returns:
        Document dict theo schema mới
    """
    # Tự động tạo base path từ job_id: ocr-results/{job_id}/images/
    auto_base_path = f"ocr-results/{job_id}/images/"
    
    # Update image paths với format mới
    for block in blocks:
        if block.get("type") == "image" and "img_path" in block:
            img_path = block["img_path"]
            # Lấy filename từ path hiện tại
            filename = os.path.basename(img_path)
            # Tạo path mới với format: ocr-results/{job_id}/images/filename
            block["img_path"] = f"{auto_base_path}{filename}"
    
    return {
        "document_id": job_id,
        "file_name": file_name,
        "total_pages": total_pages,
        "content": blocks
    }
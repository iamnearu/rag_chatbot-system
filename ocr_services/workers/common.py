#!/usr/bin/env python3
"""
Common utilities for all OCR workers (DeepSeek, Docling, MinerU)
Chứa các hàm xử lý chung để tránh duplicate code

Schema output chuẩn:
{
  "document": {
    "metadata": {"engine": "...", "job_id": "...", ...},
    "content": [
      {
        "page_number": 1,
        "blocks": [
          {"type": "paragraph", "text": "..."},
          {"type": "heading", "level": 1, "text": "..."},
          {"type": "image", "source": "..."},
          {"type": "table", "table_id": "tbl_01", "rows": [[...]], "validation": "..."}
        ]
      }
    ]
  }
}
"""

# ═══════════════════════════════════════════════════════════════════
# STANDARD LIBRARY (LIGHTWEIGHT)
# ═══════════════════════════════════════════════════════════════════
import os
import re
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# ═══════════════════════════════════════════════════════════════════
# PROJECT IMPORTS
# ═══════════════════════════════════════════════════════════════════
from app.utils.utils import apply_regex_heuristics, validate_financial_rows

# ═══════════════════════════════════════════════════════════════════
# HEAVY/LAZY IMPORTS (import bên trong hàm khi cần)
# - PIL/Image - Image processing
# - numpy, pandas - Data processing (nếu dùng)
# ═══════════════════════════════════════════════════════════════════


# =============================================================================
# NOTE: Markdown & JSON processing functions moved to app/utils/
# - clean_markdown() → app/utils/postprocess_md.py
# - parse_html_table() → app/utils/postprocess_json.py
# - process_ocr_to_blocks() → app/utils/postprocess_json.py
# - process_pages_to_document() → app/utils/postprocess_json.py
# - process_single_markdown_to_document() → app/utils/postprocess_json.py
# - validate_financial_rows() → app/utils/utils.py
#
# Workers should import these from their respective modules instead.
# This file focuses on worker-specific utilities (image handling, output saving).
# =============================================================================
# =============================================================================


# =============================================================================
# IMAGE UTILITIES (Worker-specific)
# =============================================================================

def rename_images_to_standard_format(
    source_dir: Path, 
    dest_dir: Path, 
    page_mapping: Optional[Dict[str, int]] = None
) -> Dict[str, str]:
    """
    Rename và copy images từ source sang dest với format chuẩn {page}_{idx}.jpg
    
    Returns:
        Dict mapping tên cũ -> tên mới
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    rename_map = {}
    
    if not source_dir.exists():
        return rename_map
    
    image_files = sorted([
        f for f in source_dir.iterdir() 
        if f.is_file() and f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    ])
    
    page_images = {}
    
    for img_file in image_files:
        name = img_file.stem.lower()
        page_idx = 0
        
        page_match = re.search(r'(?:page[_-]?|p[_-]?)(\d+)', name, re.IGNORECASE)
        if page_match:
            page_idx = int(page_match.group(1))
        elif page_mapping and img_file.name in page_mapping:
            page_idx = page_mapping[img_file.name]
        
        if page_idx not in page_images:
            page_images[page_idx] = []
        page_images[page_idx].append(img_file)
    
    for page_idx in sorted(page_images.keys()):
        for img_idx, img_file in enumerate(page_images[page_idx]):
            new_name = f"{page_idx}_{img_idx}.jpg"
            dest_path = dest_dir / new_name
            
            if img_file.suffix.lower() in ['.jpg', '.jpeg']:
                shutil.copy2(img_file, dest_path)
            else:
                try:
                    from PIL import Image
                    img = Image.open(img_file)
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    img.save(dest_path, 'JPEG', quality=95)
                except Exception:
                    shutil.copy2(img_file, dest_path)
            
            rename_map[img_file.name] = new_name
    
    return rename_map


def update_markdown_image_paths(markdown: str, rename_map: Dict[str, str]) -> str:
    """
    Cập nhật image paths trong markdown theo rename_map
    """
    def replace_img_path(match):
        alt = match.group(1)
        path = match.group(2)
        filename = os.path.basename(path)
        
        if filename in rename_map:
            new_filename = rename_map[filename]
            return f'![{alt}](images/{new_filename})'
        return match.group(0)
    
    return re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_img_path, markdown)


# =============================================================================
# MAIN OCR TO BLOCKS PROCESSING (Moved to app/utils/postprocess_json.py)
# =============================================================================
# process_ocr_to_blocks() → app/utils/postprocess_json.py
# process_pages_to_document() → app/utils/postprocess_json.py
# process_single_markdown_to_document() → app/utils/postprocess_json.py


# =============================================================================
# OUTPUT SAVING
# =============================================================================

def save_outputs(
    output_dir: Path,
    job_id: str,
    engine: str,
    raw_md: str,
    clean_md: str,
    document: Dict[str, Any],
    total_pages: int = 0,
    timing: Dict[str, float] = None
) -> Dict[str, str]:
    """
    Lưu outputs theo format chuẩn cho tất cả workers
    
    Files created:
    - {job_id}.md (clean markdown)
    - {job_id}.json (document structure)
    - {job_id}_result.json (metadata - internal, cleaned up by executor)
    - images/ (image files)
    
    Args:
        timing: Dict với timing data, e.g.:
            {"processing_time": 120.5, "t_pdf2img": 10.2, "t_infer": 95.0, ...}
    
    Returns:
        Dict với paths của các files đã tạo
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Vietnamese spell correction on clean markdown
    # Stage 1: Lookup table (fast, deterministic)
    try:
        from app.utils.vn_spell_corrector import correct_vietnamese_diacritics
        clean_md = correct_vietnamese_diacritics(clean_md)
    except Exception as e:
        print(f"⚠️  Vietnamese spell correction skipped: {e}")
    
    # Stage 2: ProtonX model correction (deep, context-aware)
    try:
        import time as _time
        t_spell = _time.time()
        from app.utils.vn_model_corrector import correct_with_model, unload_model as unload_protonx
        
        # DEBUG LOGGING
        with open("/tmp/ocr_debug.log", "a") as logtable:
            logtable.write(f"[{datetime.now()}] Job {job_id}: Starting ProtonX correction...\n")
        
        # Define debug report path
        debug_report_path = output_dir / f"{job_id}_correction_report.md"
            
        clean_md = correct_with_model(clean_md, debug_log_path=str(debug_report_path))
        
        t_spell = _time.time() - t_spell
        print(f"⏱️  ProtonX model correction: {t_spell:.1f}s")
        print(f"📄 Correction report: {debug_report_path}")
        
        with open("/tmp/ocr_debug.log", "a") as logtable:
            logtable.write(f"[{datetime.now()}] Job {job_id}: ProtonX finished in {t_spell:.1f}s\n")
            
        if timing is not None:
            timing["t_spell_correct"] = round(t_spell, 2)
        
        # Giải phóng ProtonX khỏi VRAM sau khi sửa xong
        unload_protonx()
        print(f"✅ ProtonX VRAM freed after correction")
    except Exception as e:
        print(f"⚠️  ProtonX model correction skipped: {e}")
        with open("/tmp/ocr_debug.log", "a") as logtable:
            logtable.write(f"[{datetime.now()}] Job {job_id}: ProtonX FAILED: {e}\n")
    
    # Clean markdown
    clean_md_path = output_dir / f"{job_id}.md"
    with open(clean_md_path, 'w', encoding='utf-8') as f:
        f.write(clean_md if clean_md else "# No content extracted\n")
    
    # Document JSON (schema chuẩn)
    doc_path = output_dir / f"{job_id}.json"
    with open(doc_path, 'w', encoding='utf-8') as f:
        json.dump(document, f, ensure_ascii=False, indent=2)
    
    # Count blocks
    total_blocks = sum(
        len(page.get("blocks", []))
        for page in document.get("document", {}).get("content", [])
    )
    
    # Result JSON (metadata)
    result_json = {
        "job_id": job_id,
        "status": "completed",
        "engine": engine,
        "total_pages": total_pages or len(document.get("document", {}).get("content", [])),
        "total_blocks": total_blocks,
        "output_files": {
            "clean_markdown": f"{job_id}.md",
            "document": f"{job_id}.json",
            "images_dir": "images/"
        },
        "processed_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Include timing data if provided
    if timing:
        result_json["timing"] = timing
    
    result_path = output_dir / f"{job_id}_result.json"
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)
    
    return {
        "clean_md": str(clean_md_path),
        "document": str(doc_path),
        "result": str(result_path)
    }

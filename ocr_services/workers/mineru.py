#!/usr/bin/env python3
"""
MinerU OCR Worker - Sử dụng mineru CLI thực sự (v2.7+)
Chạy trong conda env: mineru
"""

# ═══════════════════════════════════════════════════════════════════
# STANDARD LIBRARY (LIGHTWEIGHT)
# ═══════════════════════════════════════════════════════════════════
import sys
import json
import os
import shutil
import subprocess
import re
import time
from pathlib import Path
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════════
# PROJECT IMPORTS
# ═══════════════════════════════════════════════════════════════════
from workers.common import (
    rename_images_to_standard_format,
    update_markdown_image_paths,
    save_outputs
)

# Import từ app/utils (postprocess functions moved)
from app.utils.postprocess_md import clean_markdown
from app.utils.postprocess_json import (
    process_ocr_to_blocks,
    process_single_markdown_to_document,
    parse_html_table,
    build_document_structure
)
from app.utils.utils import validate_financial_rows

# ═══════════════════════════════════════════════════════════════════
# HEAVY/LAZY IMPORTS (import bên trong hàm khi cần)
# - pymupdf (fitz) - PDF parsing
# - numpy, PIL - Image processing (nếu dùng)
# ═══════════════════════════════════════════════════════════════════


def main(config_path: str):
    """
    Main worker function cho MinerU engine
    Sử dụng mineru CLI v2.7+ với backend pipeline
    """
    # Load config
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    input_path = config['input_path']
    output_dir = config['output_dir']
    job_id = config['job_id']
    
    print(f"🚀 [MinerU Worker] Starting with mineru CLI v2.7+...")
    print(f"   Input: {input_path}")
    print(f"   Output: {output_dir}")
    print(f"   Job ID: {job_id}")
    
    try:
        import torch
        
        # Timing tracking
        t_start = time.time()
        timing = {
            "t_pdf2img": 0.0,
            "t_preprocess": 0.0,
            "t_infer": 0.0,
            "t_postprocess": 0.0,
            "processing_time": 0.0,
        }
        
        # Check GPU
        if torch.cuda.is_available():
            print(f"✅ GPU: {torch.cuda.get_device_name(0)}")
        else:
            print("⚠️  GPU not available, using CPU")
        
        # Prepare paths
        input_path = Path(input_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Tạo thư mục tạm cho MinerU output
        temp_output = output_dir / "_mineru_temp"
        temp_output.mkdir(parents=True, exist_ok=True)
        
        original_filename = input_path.name
        file_stem = input_path.stem
        
        print(f"📄 Processing: {original_filename}")
        
        # Chạy mineru CLI với backend pipeline
        print(f"🔍 Running mineru CLI...")
        print(f"   📊 Progress: Initializing MinerU pipeline...")
        
        # Stage: Inference (CLI)
        t0 = time.time()
        
        # Determine device
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        cmd = [
            "mineru",
            "-p", str(input_path),
            "-o", str(temp_output),
            "-b", "pipeline",  # Use pipeline backend - more general, no VLM needed
            "-m", "auto",      # auto detect OCR or TXT mode
            "-d", device,      # device: cuda or cpu
            "--vram", "10",    # Max VRAM usage (GB) - user has 12GB 3060
        ]
        
        print(f"   Command: {' '.join(cmd)}")
        print(f"   📊 Progress: Running document conversion...")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes timeout
            env={**os.environ, 'DISABLE_MODEL_SOURCE_CHECK': 'True'}
        )
        
        print(f"   📊 Progress: Conversion completed")
        if result.stdout:
            # Print last few lines of stdout for progress
            lines = result.stdout.strip().split('\n')
            for line in lines[-5:]:
                if line.strip():
                    print(f"   {line}")
        if result.stderr:
            print(f"   ⚠️  stderr: {result.stderr[:200]}")
        
        if result.returncode != 0:
            print(f"⚠️  mineru exit code: {result.returncode}")
        
        print(f"✅ mineru CLI completed")
        timing["t_infer"] = round(time.time() - t0, 2)
        print(f"   ⏱️  CLI time: {timing['t_infer']}s")
        
        # Stage: Postprocess
        t0 = time.time()
        
        # Tìm thư mục output của MinerU
        # MinerU 2.7+ tạo: temp_output/filename/auto/
        # Ví dụ: temp_output/ae4fc40c35e64cc29ebb036b0330b69b_Bảo trì dự trên rủi ro/auto/
        mineru_output = None
        
        # Tìm thư mục auto trong temp_output
        # MinerU tạo thư mục với tên file (không có extension) / auto /
        auto_dirs = list(temp_output.glob("*/auto"))
        if auto_dirs:
            mineru_output = auto_dirs[0]
        else:
            # Fallback: tìm đệ quy file .md
            md_files = list(temp_output.glob("**/*.md"))
            if md_files:
                mineru_output = md_files[0].parent
        
        print(f"📁 MinerU output: {mineru_output}")
        
        # Đọc kết quả từ MinerU
        full_raw_md = ""
        all_blocks = []
        
        if mineru_output and mineru_output.exists():
            # Tìm file markdown
            md_files = list(mineru_output.glob("*.md"))
            if md_files:
                md_file = md_files[0]
                print(f"📄 Found markdown: {md_file.name}")
                with open(md_file, 'r', encoding='utf-8') as f:
                    full_raw_md = f.read()
                print(f"   Content length: {len(full_raw_md)} chars")
            
            # Tìm file content_list.json (tên file chứa _content_list.json)
            content_list_files = list(mineru_output.glob("*_content_list.json"))
            if not content_list_files:
                content_list_files = list(mineru_output.glob("*content_list*.json"))
            
            content_list = []
            if content_list_files:
                cl_file = content_list_files[0]
                print(f"📄 Found: {cl_file.name}")
                with open(cl_file, 'r', encoding='utf-8') as f:
                    content_list = json.load(f)
            
            # Rename và copy images với format chuẩn 0_0.jpg
            images_dir = output_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            
            rename_map = {}
            mineru_images = mineru_output / "images"
            if mineru_images.exists():
                print(f"📷 Renaming images to standard format...")
                rename_map = rename_images_to_standard_format(mineru_images, images_dir)
                print(f"   ✅ Renamed {len(rename_map)} images")
                for old_name, new_name in list(rename_map.items())[:5]:
                    print(f"      {old_name} -> {new_name}")
                if len(rename_map) > 5:
                    print(f"      ... and {len(rename_map) - 5} more")
            
            # Update image paths trong markdown
            if rename_map and full_raw_md:
                full_raw_md = update_markdown_image_paths(full_raw_md, rename_map)
                print(f"   ✅ Updated image paths in markdown")
            
            print(f"   📁 Images saved to: {images_dir}")
            print(f"   📁 Total images: {len(list(images_dir.glob('*')))}")
        
        # Luôn parse blocks từ markdown để giữ heading structure
        if full_raw_md:
            print("📝 Parsing blocks from markdown (preserves headings)...")
            all_blocks = process_ocr_to_blocks(full_raw_md)
        
        # Clean markdown
        print("🧹 Cleaning markdown...")
        clean_md = clean_markdown(full_raw_md) if full_raw_md else ""
        print(f"   ✅ Cleaned: {len(clean_md)} chars")
        
        # Count pages - use fitz for accurate count
        try:
            import fitz
            pdf_doc = fitz.open(str(input_path))
            page_count = len(pdf_doc)
            pdf_doc.close()
        except Exception:
            # Fallback to block estimation
            page_count = max(1, len(all_blocks) // 20) if all_blocks else 1
        
        # Build document structure theo schema mới (dùng hàm chung)
        print("📦 Building document structure...")
        document = build_document_structure(
            blocks=all_blocks,
            engine="MinerU",
            job_id=job_id,
            total_pages=page_count
        )
        
        # Lưu outputs theo format chuẩn
        print("💾 Saving outputs...")
        
        # ═══════════════════════════════════════════════════════════
        # GIẢI PHÓNG VRAM TRƯỚC KHI CHẠY ProtonX (trong save_outputs)
        # MinerU CLI chạy subprocess riêng nhưng torch vẫn có thể cache
        # ═══════════════════════════════════════════════════════════
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            vram_free = torch.cuda.mem_get_info()[0] / 1024**3
            print(f"✅ VRAM available for ProtonX: {vram_free:.1f} GB")
        
        # Finalize timing
        timing["t_postprocess"] = round(time.time() - t0, 2)
        timing["processing_time"] = round(time.time() - t_start, 2)
        print(f"⏱️  Timing: {timing}")
        
        saved_files = save_outputs(
            output_dir=output_dir,
            job_id=job_id,
            engine="mineru",
            raw_md=full_raw_md,
            clean_md=clean_md,
            document=document,
            total_pages=page_count,
            timing=timing
        )
        
        print(f"✅ Clean markdown: {job_id}.md ({len(clean_md)} chars)")
        print(f"✅ Document JSON: {job_id}.json ({len(all_blocks)} blocks)")
        
        # Cleanup temp directory
        if temp_output.exists():
            shutil.rmtree(temp_output)
            print("🗑️  Cleaned up temp directory")
        
        print(f"✅ [SUCCESS] Processing complete!")
        print(f"   📝 {len(all_blocks)} blocks extracted")
        print(f"   📷 Images in: images/")
        
        # Return result JSON path
        result_json = {
            "job_id": job_id,
            "status": "completed",
            "model": "mineru",
            "total_pages": page_count,
            "total_blocks": len(all_blocks)
        }
        return json.dumps(result_json)
        
    except Exception as e:
        print(f"❌ [ERROR] {e}")
        import traceback
        traceback.print_exc()
        
        # Save error result
        error_result = {
            "job_id": job_id,
            "status": "failed",
            "model": "mineru",
            "error": str(e),
            "failed_at": datetime.now(timezone.utc).isoformat()
        }
        
        result_path = Path(output_dir) / f"{job_id}_result.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(error_result, f, ensure_ascii=False, indent=2)
        
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python worker_mineru.py <config_path>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    result = main(config_path)
    print(result)

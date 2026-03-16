#!/usr/bin/env python3
"""
DeepSeek OCR Worker - Chạy trong conda env: vllm
Xử lý OCR bằng DeepSeek + vLLM
"""

# ═══════════════════════════════════════════════════════════════════
# STANDARD LIBRARY (LIGHTWEIGHT)
# ═══════════════════════════════════════════════════════════════════
import sys
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

# ═══════════════════════════════════════════════════════════════════
# SETUP PROJECT PATH
# ═══════════════════════════════════════════════════════════════════
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ═══════════════════════════════════════════════════════════════════
# HEAVY/LAZY IMPORTS (import bên trong hàm khi cần)
# - torch (GPU/CUDA)
# - vllm (LLM server)
# - app.services.processor, app.core.model_init
# - fitz (PDF library)
# ═══════════════════════════════════════════════════════════════════

def main(config_path: str):
    """
    Main worker function cho DeepSeek engine
    
    Args:
        config_path: Đường dẫn tới file config JSON
    """
    # Load config
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    input_path = config['input_path']
    output_dir = config['output_dir']
    job_id = config['job_id']
    
    print(f"🚀 [DeepSeek Worker] Starting...")
    print(f"   Input: {input_path}")
    print(f"   Output: {output_dir}")
    print(f"   Job ID: {job_id}")
    
    # Timing tracking
    t_start = time.time()
    timing = {
        "t_pdf2img": 0.0,
        "t_preprocess": 0.0,
        "t_infer": 0.0,
        "t_postprocess": 0.0,
        "processing_time": 0.0,
    }
    
    try:
        # Import từ đúng modules
        from app.utils.utils import pdf_to_images_high_quality
        from app.services.processor import preprocess_batch, generate_ocr
        from app.utils.postprocess_md import process_ocr_output, extract_content, clean_markdown
        from app.utils.postprocess_json import process_ocr_to_blocks, build_document_structure
        from app.core.model_init import llm, sampling_params
        from app.config import PROMPT, CHUNK_SIZE
        from workers.common import save_outputs
        import torch
        
        # Check GPU
        if torch.cuda.is_available():
            print(f"✅ GPU: {torch.cuda.get_device_name(0)}")
        else:
            print("⚠️  GPU not available")
        
        # Get PDF info
        import fitz
        doc = fitz.open(input_path)
        total_pages = len(doc)
        doc.close()
        
        print(f"📄 Total pages: {total_pages}")
        
        # Process in batches with progress logging
        all_blocks = []
        full_clean_md = ""
        full_raw_md = ""
        
        for i in range(0, total_pages, CHUNK_SIZE):
            start = i
            end = min(i + CHUNK_SIZE, total_pages)
            progress = (end / total_pages) * 100
            print(f"📦 Processing pages {start+1}-{end}/{total_pages} ({progress:.1f}%)")
            
            # Stage 1: PDF to images
            print(f"   🖼️  Converting PDF pages to images...")
            t0 = time.time()
            images = pdf_to_images_high_quality(input_path, start_page=start, end_page=end)
            timing["t_pdf2img"] += time.time() - t0
            print(f"   ✅ Got {len(images)} images ({time.time() - t0:.1f}s)")
            
            # Stage 2: Preprocess (deskew)
            print(f"   🔧 Preprocessing batch (deskew)...")
            t0 = time.time()
            batch_inputs, processed_images = preprocess_batch(images, PROMPT)
            timing["t_preprocess"] += time.time() - t0
            print(f"   ✅ Preprocessed ({time.time() - t0:.1f}s)")
            
            # Stage 3: Inference
            print(f"   🤖 Running DeepSeek OCR inference...")
            t0 = time.time()
            outputs = generate_ocr(llm, batch_inputs, sampling_params)
            timing["t_infer"] += time.time() - t0
            print(f"   ✅ Got {len(outputs)} outputs ({time.time() - t0:.1f}s)")
            
            # Stage 4: Post-process
            print(f"   📝 Post-processing outputs...")
            t0 = time.time()
            clean_md, raw_md, _ = process_ocr_output(outputs, processed_images, out_path=output_dir, start_page=start)
            full_clean_md += clean_md
            full_raw_md += raw_md if raw_md else ""
            
            # Extract blocks
            for page_offset, output in enumerate(outputs):
                raw_text = output.outputs[0].text if hasattr(output, 'outputs') else str(output)
                page_idx = start + page_offset
                cleaned = extract_content(raw_text, job_id, page_idx=page_idx)
                
                blocks = process_ocr_to_blocks(cleaned, page_idx=page_idx)
                all_blocks.extend(blocks)
            
            timing["t_postprocess"] += time.time() - t0
            print(f"   ✅ Batch complete: {len(blocks)} blocks ({time.time() - t0:.1f}s)")
            
            # Clear GPU cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        # ========== SAVE OUTPUT FILES ==========
        # Get original filename
        original_filename = Path(input_path).name
        
        # Apply markdown cleaning
        print(f"🧹 Cleaning markdown output...")
        full_clean_md = clean_markdown(full_clean_md)
        print(f"   ✅ Cleaned: {len(full_clean_md)} chars")
        
        # Build document structure theo schema mới (dùng hàm chung)
        print("📦 Building document structure...")
        document = build_document_structure(
            blocks=all_blocks,
            engine="DeepSeek",
            job_id=job_id,
            total_pages=total_pages
        )
        
        # Calculate total processing time
        timing["processing_time"] = round(time.time() - t_start, 2)
        # Round all timing values
        timing = {k: round(v, 2) for k, v in timing.items()}
        
        print(f"⏱️  Timing: {timing}")
        
        # ═══════════════════════════════════════════════════════════
        # GIẢI PHÓNG vLLM (DeepSeek) KHỎI VRAM TRƯỚC KHI CHẠY ProtonX
        # vLLM chiếm ~12GB VRAM, cần free để ProtonX có thể load
        # ═══════════════════════════════════════════════════════════
        print("🗑️  Freeing DeepSeek vLLM from VRAM...")
        import gc
        import app.core.model_init as _model_init_module
        
        # Xóa references tới vLLM model
        del llm
        _model_init_module.llm = None
        _model_init_module.sampling_params = None
        
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        vram_free = torch.cuda.mem_get_info()[0] / 1024**3 if torch.cuda.is_available() else 0
        print(f"✅ vLLM freed! VRAM available: {vram_free:.1f} GB")
        
        # Save using common save_outputs (includes timing in result JSON)
        # ProtonX sẽ được load bên trong save_outputs() khi VRAM đã trống
        saved_files = save_outputs(
            output_dir=output_dir,
            job_id=job_id,
            engine="deepseek",
            raw_md=full_raw_md,
            clean_md=full_clean_md,
            document=document,
            total_pages=total_pages,
            timing=timing
        )
        
        print(f"✅ [DeepSeek Worker] Completed! Blocks: {len(all_blocks)}")
        print(f"   Output files:")
        for key, path in saved_files.items():
            print(f"   - {key}: {path}")
        print(f"   - images: {output_dir}/images/")
        
        return 0
        
    except Exception as e:
        print(f"❌ [DeepSeek Worker] Error: {e}")
        import traceback
        traceback.print_exc()
        
        return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python worker_deepseek.py <config_json_path>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    exit_code = main(config_path)
    sys.exit(exit_code)

#!/usr/bin/env python3
"""
Docling OCR Worker - Optimized
- OCR: RapidOCR + CUDA Acceleration (Fastest)
- Output: Standardized to match MinerU/DeepSeek structure
"""

import sys
import json
import os
import shutil
import re
import time
from pathlib import Path
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════════
# SETUP PROJECT PATH
# ═══════════════════════════════════════════════════════════════════
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from workers.common import save_outputs
from app.utils.postprocess_md import clean_markdown
from app.utils.postprocess_json import process_ocr_to_blocks, build_document_structure

def main(config_path: str):
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    input_path = config['input_path']
    output_dir = config['output_dir']
    job_id = config['job_id']
    
    print(f"🚀 [Docling Worker] Starting (Optimized)...")
    print(f"   Input: {input_path}")
    print(f"   Job ID: {job_id}")
    
    try:
        import torch
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions, 
            AcceleratorOptions, 
            AcceleratorDevice
        )
        from docling.datamodel.base_models import InputFormat
        from docling_core.types.doc.base import ImageRefMode
        
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
        device = AcceleratorDevice.CPU
        if torch.cuda.is_available():
            print(f"✅ GPU: {torch.cuda.get_device_name(0)}")
            device = AcceleratorDevice.CUDA
        
        # Create output directories
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        images_dir = output_path / "images"
        images_dir.mkdir(exist_ok=True)
        
        # === PIPELINE CONFIGURATION ===
        print("📦 Configuring Docling pipeline...")
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options.do_cell_matching = True
        pipeline_options.images_scale = 2.0
        pipeline_options.generate_picture_images = True
        pipeline_options.generate_page_images = False
        
        # ACCELERATION
        pipeline_options.accelerator_options = AcceleratorOptions(
            num_threads=4, device=device
        )
        
        # FAST OCR (RapidOCR) if available
        try:
            from docling.datamodel.pipeline_options import RapidOcrOptions
            pipeline_options.ocr_options = RapidOcrOptions()
            print("   ⚡ OCR Engine: RapidOCR (Fast)")
        except ImportError:
            print("   ⚠️  RapidOCR not found, using default (EasyOCR/Tesseract)")

        # Converter
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        # Convert (Inference)
        print("📦 Converting document...")
        t0 = time.time()
        result = converter.convert(input_path)
        timing["t_infer"] = round(time.time() - t0, 2)
        print(f"   ⏱️  Conversion time: {timing['t_infer']}s")
        
        if not result or not result.document:
            raise RuntimeError("Empty result from Docling")
            
        doc = result.document
        
        # === POST-PROCESS ===
        t0 = time.time()
        
        # 1. Export Markdown with Images to temporary location
        print("📝 Exporting markdown & extracting images...")
        temp_artifacts = output_path / "_temp_artifacts"
        temp_artifacts.mkdir(exist_ok=True)
        
        temp_md_path = output_path / f"{job_id}_temp.md"
        doc.save_as_markdown(
            filename=str(temp_md_path),
            artifacts_dir=temp_artifacts,
            image_mode=ImageRefMode.REFERENCED
        )
        
        with open(temp_md_path, 'r', encoding='utf-8') as f:
            raw_markdown = f.read()
            
        # Cleanup temp md
        temp_md_path.unlink(missing_ok=True)
        
        # 2. Rename & Move Images to Standard Format
        print("🖼️  Processing images...")
        image_mapping = {} # old_name -> new_name
        
        # Find images in artifacts
        found_images = sorted(list(temp_artifacts.glob("*"))) 
        # Filter only images
        valid_exts = {'.jpg', '.jpeg', '.png', '.webp'}
        found_images = [p for p in found_images if p.suffix.lower() in valid_exts]
        
        # Rename logic: {page_idx}_{img_idx}.jpg
        # Since Docling artifacts don't have page info in filename easily, 
        # we index them sequentially. Ideally we'd map back to page, but sequential "0_i.jpg" is safe enough for display.
        # Note: Docling v2 exports images as 'picture_1.png', 'table_1.png'.
        
        for idx, img_path in enumerate(found_images):
            new_name = f"0_{idx}.jpg" # Use page 0 as default container
            dest_path = images_dir / new_name
            
            # Convert/Copy
            try:
                from PIL import Image
                with Image.open(img_path) as img:
                    if img.mode in ('RGBA', 'P'): img = img.convert('RGB')
                    img.save(dest_path, quality=95)
                image_mapping[img_path.name] = new_name
            except Exception as e:
                print(f"   ⚠️ Error converting {img_path.name}: {e}")
        
        # Cleanup artifacts
        shutil.rmtree(temp_artifacts, ignore_errors=True)
        
        # 3. Update Markdown Paths
        print("📝 Update image paths in markdown...")
        md_cleaned = raw_markdown
        
        # Regex to match ![alt](path)
        # We replace the 'path' part
        def replace_img_path(match):
            alt = match.group(1)
            path = match.group(2)
            fname = Path(path).name
            
            if fname in image_mapping:
                # Found mapped image
                new_path = f"images/{image_mapping[fname]}"
                return f"![{alt}]({new_path})"
            return match.group(0) # No change
            
        md_cleaned = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_img_path, md_cleaned)
            
        # 4. Clean Markdown (tables, etc)
        print("🧹 Cleaning markdown...")
        md_cleaned = clean_markdown(md_cleaned)
        
        # 5. Extract Blocks (Schema Standard)
        print("📦 Extracting blocks...")
        blocks = process_ocr_to_blocks(md_cleaned)
        
        # Count pages
        try:
            import fitz
            with fitz.open(str(input_path)) as pdf:
                total_pages = len(pdf)
        except:
            total_pages = 1
            
        # 6. Build Document Structure
        document = build_document_structure(
            blocks=blocks,
            engine="Docling",
            job_id=job_id,
            total_pages=total_pages
        )
        
        # ═══════════════════════════════════════════════════════════
        # GIẢI PHÓNG DOCLING MODELS KHỎI VRAM TRƯỚC KHI CHẠY ProtonX
        # ═══════════════════════════════════════════════════════════
        print("🗑️  Freeing Docling models from VRAM...")
        import gc
        del converter
        del result
        del doc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            vram_free = torch.cuda.mem_get_info()[0] / 1024**3
            print(f"✅ Docling freed! VRAM available: {vram_free:.1f} GB")
        
        # 7. Save Outputs
        timing["t_postprocess"] = round(time.time() - t0, 2)
        timing["processing_time"] = round(time.time() - t_start, 2)
        print(f"⏱️  Timing: {timing}")
        
        save_outputs(
            output_dir=output_path,
            job_id=job_id,
            engine="docling",
            raw_md=md_cleaned,
            clean_md=md_cleaned, # Spell correction happens inside here
            document=document,
            total_pages=total_pages,
            timing=timing
        )
        
        print("\n✅ [Docling Worker] Completed!")
        return 0
        
    except Exception as e:
        print(f"❌ [Docling Worker] Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Save error
        result_path = Path(output_dir) / f"{job_id}_result.json"
        with open(result_path, 'w') as f:
            json.dump({"status": "failed", "error": str(e)}, f)
        return 1

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python docling_worker.py <config>")
        sys.exit(1)
    main(sys.argv[1])

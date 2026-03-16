"""
Vietnamese Model Corrector - Sửa dấu tiếng Việt bằng ProtonX Seq2Seq model (Optimized)

Model: protonx-models/protonx-legal-tc (Teacher model)
Optimization:
- FP16 (half precision) on CUDA
- Batch inference (processing multiple lines/chunks at once)
- Dynamic batching
"""

import re
import logging
import torch
from typing import List, Tuple

_log = logging.getLogger(__name__)

# Singleton
_model = None
_tokenizer = None
_device = None

# Config
BATCH_SIZE = 32  # Process 32 chunks at a time
CHUNK_WORD_SIZE = 64
MAX_NEW_TOKENS = 160

# Skip patterns (same as before)
_SKIP_PATTERNS = [
    re.compile(r'^\s*$'),
    # re.compile(r'^\s*#'),
    re.compile(r'^\s*!\[|^\s*\['),
    re.compile(r'^\s*<'),
    re.compile(r'^\s*[-*+]\s*$'),
    re.compile(r'^\s*\|'),
    re.compile(r'^\s*```'),
    re.compile(r'^\s*---'),
    re.compile(r'^\s*\d+\.\s*$'),
    re.compile(r'^https?://'),
    re.compile(r'^[A-Za-z0-9.@:/\-_]+$'),
]

def _load_model():
    global _model, _tokenizer, _device
    if _model: return _model, _tokenizer, _device
    
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    
    model_path = "protonx-models/protonx-legal-tc"
    _log.info(f"🔤 Loading ProtonX model (FP16)...")
    
    _tokenizer = AutoTokenizer.from_pretrained(model_path)
    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # Load in FP16 if on CUDA to save memory & speed up
    torch_dtype = torch.float16 if _device.type == 'cuda' else torch.float32
    
    _model = AutoModelForSeq2SeqLM.from_pretrained(model_path, torch_dtype=torch_dtype)
    _model.to(_device)
    _model.eval()
    
    return _model, _tokenizer, _device


def unload_model():
    """Giải phóng ProtonX model khỏi VRAM sau khi sửa xong."""
    global _model, _tokenizer, _device
    import gc
    
    if _model is not None:
        del _model
        _model = None
    if _tokenizer is not None:
        del _tokenizer
        _tokenizer = None
    _device = None
    
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    _log.info("🗑️  ProtonX model unloaded from VRAM")

def _should_skip_line(line: str) -> bool:
    for p in _SKIP_PATTERNS:
        if p.match(line): return True
    return False

def _decode_batch(texts: List[str]) -> List[str]:
    """Decode a batch of texts."""
    if not texts: return []
    
    model, tokenizer, device = _load_model()
    
    # Tokenize batch
    inputs = tokenizer(
        texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=MAX_NEW_TOKENS
    ).to(device)
    
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            num_beams=4,  # Increased to 4 for better accuracy (was 2)
            max_new_tokens=MAX_NEW_TOKENS,
            early_stopping=True
        )
        
    return tokenizer.batch_decode(outputs, skip_special_tokens=True)

def correct_with_model(text: str, debug_log_path: str = None) -> str:
    if not text: return text
    
    lines = text.split('\n')
    
    # Identify lines to process and their chunks
    # Structure: [ (line_idx, indent, bullet, [chunk1, chunk2, ...]) ]
    lines_to_process = []
    
    # Flat list of all chunks to send to model
    all_chunks_text = []
    
    # Debug info storage
    line_status = [] # {idx, type, original, corrected, action}
    
    # DEBUG LOG (Raw)
    with open("/tmp/ocr_debug_lines.log", "w") as f:
        f.write(f"--- BATCH CORRECTING {len(lines)} LINES ---\n")
    
    for idx, line in enumerate(lines):
        line_content = line.strip()
        
        # 1. EMPTY LINES
        if not line_content:
            line_status.append({
                "idx": idx, "type": "Empty", "action": "SKIP", 
                "original": line, "corrected": line
            })
            continue
            
        # 2. SKIP PATTERNS
        if _should_skip_line(line):
            with open("/tmp/ocr_debug_lines.log", "a") as f:
                f.write(f"SKIP : {line[:50]}...\n")
            
            # Detect type for report
            # Header check removed here since we process them now
            if line_content.startswith('!['): ltype = "Image"
            elif line_content.startswith('|'): ltype = "Table"
            elif line_content.startswith('```'): ltype = "Code"
            else: ltype = "Markdown"
            
            line_status.append({
                "idx": idx, "type": ltype, "action": "SKIP", 
                "original": line, "corrected": line
            })
            continue
            
        # 3. TEXT TO PROCESS
        # Parse formatting
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        
        # Updated regex to match bullets OR headers (#)
        bullet_match = re.match(r'^([-*+]\s+|\d+\.\s+|#+\s*)', stripped)
        if bullet_match:
            bullet = bullet_match.group(0)
            content = stripped[len(bullet):]
            # print(f"DEBUG: Line {idx} Content='{content}' Bullet='{bullet}'") 
        else:
            bullet = ""
            content = stripped
            
        if not content.strip():
            # Should be caught by empty check but just in case
            line_status.append({
                "idx": idx, "type": "Empty", "action": "SKIP", 
                "original": line, "corrected": line
            })
            continue
            
        # Chunking
        words = content.split()
        chunks = []
        if len(words) <= CHUNK_WORD_SIZE:
            chunks.append(content)
        else:
            for i in range(0, len(words), CHUNK_WORD_SIZE):
                chunks.append(" ".join(words[i:i + CHUNK_WORD_SIZE]))
                
        lines_to_process.append({
            "line_idx": idx,
            "indent": indent,
            "bullet": bullet,
            "chunk_count": len(chunks),
            "start_chunk_idx": len(all_chunks_text) # Pointer to where its chunks start in flat list
        })
        all_chunks_text.extend(chunks)
        
        # Placeholder for status (will update after correction)
        line_status.append({
            "idx": idx, "type": "Text", "action": "FIX_PENDING", 
            "original": line, "corrected": None
        })

    # If nothing to process but we need report
    if not all_chunks_text:
        # Generate report even if no text to correct
        if debug_log_path:
            _write_debug_report(debug_log_path, line_status)
        return text

    # Batch Process
    corrected_chunks = []
    total = len(all_chunks_text)
    
    for i in range(0, total, BATCH_SIZE):
        batch = all_chunks_text[i : i + BATCH_SIZE]
        decoded = _decode_batch(batch)
        corrected_chunks.extend(decoded)
        print(f"   ⚡ Processed batch {i}-{i+len(batch)}/{total}")

    # Reconstruct lines
    result_lines = list(lines) # Copy original
    count_corrected = 0
    
    for item in lines_to_process:
        idx = item['line_idx']
        start = item['start_chunk_idx']
        count = item['chunk_count']
        
        corrected_parts = corrected_chunks[start : start + count]
        corrected_content = " ".join(corrected_parts)
        
        new_line = item['indent'] + item['bullet'] + corrected_content
        
        # Update status
        status_entry = next((x for x in line_status if x["idx"] == idx), None)
        if status_entry:
            status_entry["corrected"] = new_line
            if new_line != result_lines[idx]:
                status_entry["action"] = "FIXED"
                count_corrected += 1
                with open("/tmp/ocr_debug_lines.log", "a") as f:
                    f.write(f"FIXED: {result_lines[idx][:50]}... -> {new_line[:50]}...\n")
            else:
                status_entry["action"] = "SAME"
                with open("/tmp/ocr_debug_lines.log", "a") as f:
                    f.write(f"SAME : {result_lines[idx][:50]}...\n")
                
        result_lines[idx] = new_line
        
    print(f"🔤 ProtonX Batch: corrected {count_corrected} lines")
    
    # Write full report if requested
    if debug_log_path:
        _write_debug_report(debug_log_path, line_status)

    return "\n".join(result_lines)


def _write_debug_report(path: str, line_status: List[dict]):
    """Write detailed markdown report of corrections"""
    import time
    try:
        lines = []
        lines.append(f"# ProtonX Correction Debug Report")
        lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Total Lines: {len(line_status)}\n")
        
        lines.append("## Correction Detail")
        lines.append("| Line | Type | Action | Original | Corrected (Final) |")
        lines.append("|---|---|---|---|---|")
        
        for item in line_status:
            idx = item["idx"] + 1
            ltype = item.get("type", "?")
            action = item.get("action", "?")
            orig = item.get("original", "").strip().replace("|", "\|")
            corr = item.get("corrected", "")
            if corr is None: corr = orig # For skipped lines
            corr = corr.strip().replace("|", "\|")
            
            # Truncate if too long (table display issue)
            if len(orig) > 50: orig = orig[:47] + "..."
            if len(corr) > 50: corr = corr[:47] + "..."
            
            if action == "FIXED":
                action_display = "**FIXED**"
            elif action == "SKIP":
                action_display = "SKIP"
            else:
                action_display = action
            
            lines.append(f"| {idx} | {ltype} | {action_display} | `{orig}` | `{corr}` |")
            
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"✅ Generated debug report: {path}")
    except Exception as e:
        _log.warning(f"Failed to write debug report: {e}")


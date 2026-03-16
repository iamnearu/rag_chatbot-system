
import sys
import os
import re
import time

# Add project root to path
sys.path.insert(0, "/home/cuongnh/cuong/ocr_services")

from app.utils.vn_model_corrector import _load_model, _decode_batch, _should_skip_line, CHUNK_WORD_SIZE, BATCH_SIZE

def debug_correction(text, output_file):
    print(f"🚀 Starting debug correction...")
    print(f"📝 Output file: {output_file}")
    
    lines = text.split('\n')
    
    # Structure for debug report
    report_lines = []
    report_lines.append(f"# ProtonX Correction Debug Report")
    report_lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Prepare for batch processing
    lines_to_process = []
    all_chunks_text = [] # Flat list of chunks
    
    # 1. CHUNKING PHASE
    report_lines.append("## 1. Chunking Phase\n")
    
    for idx, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue
            
        if _should_skip_line(line):
            report_lines.append(f"- **Line {idx+1}**: `SKIP` (Markdown/Special syntax)")
            report_lines.append(f"  > *{line_stripped}*")
            continue
            
        # Parse formatting
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        bullet_match = re.match(r'^([-*+]\s+|\d+\.\s+)', stripped)
        
        prefix = indent
        if bullet_match:
            bullet = bullet_match.group(0)
            content = stripped[len(bullet):]
            prefix += bullet
        else:
            content = stripped
            
        if not content.strip():
            continue

        # Chunking Logic
        words = content.split()
        chunks = []
        if len(words) <= CHUNK_WORD_SIZE:
             chunks.append(content)
        else:
             for i in range(0, len(words), CHUNK_WORD_SIZE):
                 chunks.append(" ".join(words[i:i + CHUNK_WORD_SIZE]))
                 
        # Store metadata
        lines_to_process.append({
            "line_idx": idx,
            "original_line": line,
            "prefix": prefix, 
            "chunks": chunks,          # Original chunks
            "start_idx": len(all_chunks_text)
        })
        all_chunks_text.extend(chunks)
        
        # Log chunking info
        report_lines.append(f"- **Line {idx+1}**: {len(chunks)} chunk(s)")
        report_lines.append(f"  > Original: `{line_stripped}`")
        for c_i, chunk in enumerate(chunks):
             report_lines.append(f"  - Chunk {c_i+1}: `{chunk}`")
        report_lines.append("")

    # 2. INFERENCE PHASE
    report_lines.append("## 2. Inference Phase (Batch Processing)\n")
    report_lines.append(f"Total chunks to process: {len(all_chunks_text)}")
    
    corrected_chunks_flat = []
    
    # Load model once
    t0 = time.time()
    _load_model()
    print(f"✅ Model loaded ({time.time() - t0:.2f}s)")
    
    # Run batches
    for i in range(0, len(all_chunks_text), BATCH_SIZE):
        batch = all_chunks_text[i : i + BATCH_SIZE]
        decoded_batch = _decode_batch(batch)
        corrected_chunks_flat.extend(decoded_batch)
        
        report_lines.append(f"### Batch {i // BATCH_SIZE + 1} ({len(batch)} items)")
        for b_i, (orig, corr) in enumerate(zip(batch, decoded_batch)):
            status = "✅ CHANGED" if orig != corr else "same"
            report_lines.append(f"- **Item {i + b_i + 1}**: {status}")
            report_lines.append(f"  - In : `{orig}`")
            report_lines.append(f"  - Out: `{corr}`")
        report_lines.append("")

    # 3. RECONSTRUCTION PHASE
    report_lines.append("## 3. Final Reconstruction\n")
    
    final_output_lines = []
    
    # Reconstruct
    chunk_ptr = 0
    # Map back
    for item in lines_to_process:
        start = item['start_idx']
        count = len(item['chunks'])
        
        corrected_parts = corrected_chunks_flat[start : start + count]
        corrected_content = " ".join(corrected_parts)
        final_line = item['prefix'] + corrected_content
        
        report_lines.append(f"- **Line {item['line_idx']+1}**:")
        report_lines.append(f"  - Orig: `{item['original_line'].strip()}`")
        report_lines.append(f"  - Corr: `{final_line.strip()}`")
        report_lines.append("")
        
        final_output_lines.append(final_line)
        
    # Write report
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
        
    print(f"✅ Report generated: {output_file}")


if __name__ == "__main__":
    input_text = """
MỘ ĐẠU 
mộ đạu 
NGUYÊN TẮC VẬN HÀNH VÀ BẢO TRỊ
NỘI DUNG QUY TRÌNH BẢO TRÌ HỆ
NHIỆM VỰ CỦA BAN QUẢN LÝ KHI VẬN
KIÊM TRA GIÊNG THANG & PHÍA TRÊN CABIN
KIỂM TRA ĐÁY GIẾNG THANG VÀ DƯỚI CABIN
BẢO TRỊ BÊN TRONG CABIN
BẢO TRỊ, BẢO DƯỠNG NGOÀI CỦA TÀNG
BẢO TRỊ TRẠM BIỂN ÁP HẠ THẾ
VẬN HÀNH BỘ TỰ BÙ
HỆ THỐNG PHÂN PHỐI DIỆN ĐẾN CÁC
MẬT ĐIỆN DO MẬT ĐIỆN LUỐI
QUY TRỊNH BẢO TRỊ HỆ THỐNG
QUY TRỊNH BẢO TRỊ HỆ THỐNG ĐIỆN NHỆ
QUY TRỊNH BẢO TRỊ HỆ THỐNG MẠNG LAN.
    """
    
    output_path = "/home/cuongnh/cuong/ocr_services/test/debug_report.md"
    debug_correction(input_text, output_path)

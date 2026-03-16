
import sys
import re
import time
from typing import List

# Setup path
sys.path.insert(0, "/home/cuongnh/cuong/ocr_services")

from app.utils.vn_model_corrector import _load_model, _decode_batch, _should_skip_line, BATCH_SIZE

def process_markdown_and_explain(input_file, explanation_file, output_md_file):
    print(f"🚀 Processing: {input_file}")
    
    with open(input_file, 'r', encoding='utf-8') as f:
        text = f.read()
        
    lines = text.split('\n')
    
    explanation = []
    explanation.append(f"# Markdown Processing Explanation")
    explanation.append(f"Input: `{input_file}`\n")
    explanation.append("| Line | Type | Action | Content | Note |")
    explanation.append("|---|---|---|---|---|")
    
    lines_to_process = []
    annotated_lines = []
    
    # 1. FILTERING & PREPARATION
    for idx, line in enumerate(lines):
        line_content = line.strip()
        if not line_content: # Empty line
             explanation.append(f"| {idx+1} | Empty | SKIP | (Empty Line) | Giữ nguyên |")
             annotated_lines.append({"idx": idx, "orig": line, "action": "SKIP", "final": line})
             continue
             
        if _should_skip_line(line):
             # Detect reason
             if line_content.startswith('#'): reason = "Header"
             elif line_content.startswith('!['): reason = "Image"
             elif line_content.startswith('|'): reason = "Table"
             elif line_content.startswith('```'): reason = "Code Block"
             else: reason = "Markdown Syntax"
             
             explanation.append(f"| {idx+1} | {reason} | SKIP | `{line_content[:30]}...` | Giữ nguyên format |")
             annotated_lines.append({"idx": idx, "orig": line, "action": "SKIP", "final": line})
             continue
             
        # Prose text -> Add to queue
        explanation.append(f"| {idx+1} | Text | **FIX** | `{line_content[:30]}...` | **Gửi vào Model** |")
        
        # Simple extraction logic (simplified vs full module for demo)
        prefix = ""
        content = line
        
        # Check bullet
        match = re.match(r'^(\s*[-*+]\s+)', line)
        if match:
            prefix = match.group(1)
            content = line[len(prefix):]
            
        lines_to_process.append({
            "idx": idx,
            "orig": line,
            "prefix": prefix,
            "content": content,
            "final": None # Filled later
        })
        annotated_lines.append({"idx": idx, "orig": line, "action": "FIX", "ptr": lines_to_process[-1]})

    # 2. BATCH CORRECTION
    if lines_to_process:
        print(f"🔄 Correcting {len(lines_to_process)} text lines...")
        _load_model()
        
        chunks = [item["content"] for item in lines_to_process]
        
        # Batch inference
        corrected_chunks = []
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i : i + BATCH_SIZE]
            decoded = _decode_batch(batch)
            corrected_chunks.extend(decoded)
            
        # Reconstruct
        for i, item in enumerate(lines_to_process):
            item["final"] = item["prefix"] + corrected_chunks[i]
            
    # 3. FINAL OUTPUT GENERATION
    final_output_lines = []
    
    explanation.append("\n## Result Comparison\n")
    explanation.append("| Line | Original | Corrected (Final) | Status |")
    explanation.append("|---|---|---|---|")
    
    for item in annotated_lines:
        orig = item["orig"]
        if item["action"] == "SKIP":
            final = item["final"]
            status = "Giữ nguyên"
        else:
            final = item["ptr"]["final"]
            if final != orig:
                status = "**Đã sửa**"
            else:
                status = "Không đổi"
                
            explanation.append(f"| {item['idx']+1} | `{orig.strip()}` | `{final.strip()}` | {status} |")
            
        final_output_lines.append(final)
        
    # Write files
    with open(explanation_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(explanation))
        
    with open(output_md_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_output_lines))

    print(f"✅ Created explanation: {explanation_file}")
    print(f"✅ Created final md: {output_md_file}")

if __name__ == "__main__":
    process_markdown_and_explain(
        "/home/cuongnh/cuong/ocr_services/test/sample.md",
        "/home/cuongnh/cuong/ocr_services/test/process_explanation.md",
        "/home/cuongnh/cuong/ocr_services/test/sample_corrected.md"
    )

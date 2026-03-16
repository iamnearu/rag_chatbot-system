"""
Vietnamese Spell Corrector - Sửa lỗi dấu tiếng Việt từ OCR

Các bước xử lý:
1. Thay thế ký tự lạ (Hangul, Cyrillic, etc.) → ký tự Việt
2. Sửa từ sai dấu phổ biến từ OCR (lookup table)
3. Regex patterns sửa lỗi hệ thống
"""

import re
from typing import Dict

# ═══════════════════════════════════════════════════════════════════
# 1. BẢNG THAY THẾ KÝ TỰ LẠ
# OCR đôi khi nhận dấu tiếng Việt thành ký tự Unicode khác
# ═══════════════════════════════════════════════════════════════════
FOREIGN_CHAR_MAP: Dict[str, str] = {
    # Hangul (Korean) → Vietnamese
    '받': 'nhi',  # e.g. "ngày càng받i" → "ngày càngnhii" (handled by regex below)
    '혀': 'hiể',
    '넓': 'nhiề',
    # Cyrillic → Vietnamese
    'з': 'ì',
    'м': 'm',
    'и': 'i',
    'н': 'n',
    'р': 'r',
    'с': 'c',
    'о': 'o',
    'е': 'e',
    'а': 'a',
    'у': 'y',
    # Other common OCR artifacts
    '—': '-',
    '–': '-',
    '\u200b': '',  # zero-width space
    '\ufeff': '',  # BOM
}


# ═══════════════════════════════════════════════════════════════════
# 2. BẢNG LỖI DẤU PHỔ BIẾN TỪ OCR
# Format: "từ sai" → "từ đúng"
# Chỉ sửa các từ rõ ràng sai, tránh false positive
# ═══════════════════════════════════════════════════════════════════
DIACRITICS_CORRECTIONS: Dict[str, str] = {
    # --- Dấu hỏi/ngã bị mất hoặc sai ---
    'hồng hóc': 'hỏng hóc',
    'hồng hoc': 'hỏng hóc',
    'hông hóc': 'hỏng hóc',
    
    # --- Dấu nặng bị mất ---
    'dân đến': 'dẫn đến',
    'dân đên': 'dẫn đến',
    'dẫn đên': 'dẫn đến',
    
    # --- Dấu sắc/huyền bị sai ---
    'nói dầu': 'nói đầu',
    'lòi nói': 'lời nói',
    'giói thiêu': 'giới thiệu',
    'giói thiệu': 'giới thiệu',
    'giới thiêu': 'giới thiệu',
    
    # --- Phần mềm ---
    'phàn mêm': 'phần mềm',
    'phản mêm': 'phần mềm',
    'phàn mềm': 'phần mềm',
    'phản mềm': 'phần mềm',
    
    # --- Các từ thường sai ---
    'tзм hiêu': 'tìm hiểu',
    'tìm hiêu': 'tìm hiểu',
    'tim hiểu': 'tìm hiểu',
    'nghìêm trọng': 'nghiêm trọng',
    'nghệm trọng': 'nghiêm trọng',
    'tôi ưu': 'tối ưu',
    'tôi đa': 'tối đa',
    'tôi ưu hóa': 'tối ưu hóa',
    
    # Dấu bị lệch
    'thập': 'thấp',  # chỉ sửa khi đi với "rủi ro" → handled by regex
    'theo đổi': 'theo dõi',
    'đổi ngữ': 'đội ngũ',
    'đổi với': 'đối với',
    'đổi hướng': 'đối hướng',
    
    # Từ bị sai dấu phổ biến trong tài liệu kỹ thuật
    'trình bayer': 'trình bày',
    'trình bàyer': 'trình bày',
    'giám chi phí': 'giảm chi phí',
    'giám bót': 'giảm bớt',
    'giám rủi ro': 'giảm rủi ro',
    'giám thiếu': 'giảm thiểu',
    'giám thiêu': 'giảm thiểu',
    'giám mức': 'giảm mức',
    'giám chị': 'giảm chỉ',
    'giám tần': 'giảm tần',
    
    'tiết kiểm': 'tiết kiệm',
    'tinh gơn': 'tinh gọn',
    
    'người lực': 'nguồn lực',
    'phòng vấn': 'phỏng vấn',
    'phống vấn': 'phỏng vấn',
    
    'làm thẻ nào': 'làm thế nào',
    'như thể nào': 'như thế nào',
    
    'nền tàng': 'nền tảng',
    'vât tư': 'vật tư',
    'vẻu tổ': 'yếu tố',
    
    # Dấu bị đặt sai vị trí
    'độ tin cây': 'độ tin cậy',
    'cho thây': 'cho thấy',
    'được mô tà': 'được mô tả',
    'chị ra': 'chỉ ra',
    'chị số': 'chỉ số',
    'chị định': 'chỉ định',
    'chỉ ra ràng': 'chỉ ra rằng',
    'kỳ vọng ràng': 'kỳ vọng rằng',
    
    'điều hưống': 'điều hướng',
    'ánh hương': 'ảnh hưởng',
    
    'miền phí': 'miễn phí',
    'miền bắc': 'miền Bắc',
    'miền nam': 'miền Nam',
    
    'xe đâu kéo': 'xe đầu kéo',
    'bàng cách': 'bằng cách',
    'nhìêm vụ': 'nhiệm vụ',
    'nhiệm doanh': 'nhiều doanh',
    'dựa đưa trên': 'dựa trên',
    'đưa trên': 'dựa trên',
    
    # Tên riêng / sản phẩm
    'tăng 07': 'tầng 07',
}


# ═══════════════════════════════════════════════════════════════════
# 3. REGEX PATTERNS
# Sửa lỗi hệ thống bằng regex (context-aware)
# ═══════════════════════════════════════════════════════════════════
REGEX_CORRECTIONS = [
    # "rủi ro thập" → "rủi ro thấp" (chỉ sửa "thập" khi đi với "rủi ro")
    (re.compile(r'rủi\s+ro\s+thập', re.IGNORECASE), 'rủi ro thấp'),
    
    # "hiều" → "hiểu" khi đứng sau "có thể" hoặc "để"
    (re.compile(r'(có\s+thể|để)\s+hiều'), r'\1 hiểu'),
    
    # "cận bằng" → "cân bằng" 
    (re.compile(r'cận\s+bằng'), 'cân bằng'),
    
    # "chơn" → "chọn" (trong context quyết định)
    (re.compile(r'có\s+thể\s+chơn'), 'có thể chọn'),
    
    # Trải Nghiêm → Trải Nghiệm
    (re.compile(r'[Nn]ghiêm\b(?!\s+trọng)'), lambda m: m.group(0).replace('iêm', 'iệm')),
]


def correct_vietnamese_diacritics(text: str) -> str:
    """
    Sửa lỗi dấu tiếng Việt trong text OCR.
    
    Pipeline:
    1. Thay thế ký tự lạ (Hangul, Cyrillic)
    2. Lookup table sửa từ sai dấu
    3. Regex patterns context-aware
    
    Args:
        text: Markdown text từ OCR
        
    Returns:
        Text đã sửa dấu
    """
    if not text:
        return text
    
    corrected = text
    corrections_made = 0
    
    # Step 1: Replace foreign characters
    for foreign, viet in FOREIGN_CHAR_MAP.items():
        if foreign in corrected:
            count = corrected.count(foreign)
            corrected = corrected.replace(foreign, viet)
            corrections_made += count
    
    # Step 2: Dictionary-based corrections (case-insensitive where safe)
    for wrong, right in DIACRITICS_CORRECTIONS.items():
        # Case-insensitive search, preserve original case pattern
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        matches = pattern.findall(corrected)
        if matches:
            for match in matches:
                # Preserve capitalization of first letter
                if match[0].isupper() and right[0].islower():
                    replacement = right[0].upper() + right[1:]
                else:
                    replacement = right
                corrected = corrected.replace(match, replacement, 1)
                corrections_made += 1
    
    # Step 3: Regex-based corrections
    for pattern, replacement in REGEX_CORRECTIONS:
        new_text = pattern.sub(replacement, corrected)
        if new_text != corrected:
            corrections_made += 1
            corrected = new_text
    
    if corrections_made > 0:
        print(f"🔤 Vietnamese spell correction: {corrections_made} corrections made")
    
    return corrected

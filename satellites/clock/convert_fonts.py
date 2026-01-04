import pygame
import os
import sys

pygame.font.init()

SOURCE_DIR = 'font'
OUTPUT_DIR = 'lib_fonts'

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def get_glyph_surface(font, char):
    try:
        surf = font.render(char, False, (255, 255, 255), (0, 0, 0))
        return surf
    except:
        return None

def scan_metrics(font, chars):
    min_y = 1000
    max_y = -1000
    max_digit_w = 0
    
    for char in chars:
        surf = get_glyph_surface(font, char)
        if surf is None: continue
        
        w = surf.get_width()
        h = surf.get_height()
        
        # Check ink Y
        char_min_y = h
        char_max_y = 0
        has_ink = False
        
        for y in range(h):
            for x in range(w):
                if surf.get_at((x, y))[0] > 127:
                    if y < char_min_y: char_min_y = y
                    if y > char_max_y: char_max_y = y
                    has_ink = True
        
        if has_ink:
            if char_min_y < min_y: min_y = char_min_y
            if char_max_y > max_y: max_y = char_max_y
        
        if char in "0123456789":
            if w > max_digit_w: max_digit_w = w
            
    return min_y, max_y, max_digit_w

def convert_char(font, char, crop_y, max_digit_w, target_h):
    surf = get_glyph_surface(font, char)
    if surf is None: return None, 0, 0
    
    w = surf.get_width()
    h = surf.get_height()
    
    # Determine output width
    out_w = w
    offset_x = 0
    
    # Monospace for digits
    if char in "0123456789":
        out_w = max_digit_w
        offset_x = (max_digit_w - w) // 2
    
    pages = (target_h + 7) // 8
    buffer = bytearray(pages * out_w)
    
    for x_out in range(out_w):
        x_src = x_out - offset_x
        if 0 <= x_src < w:
            for page in range(pages):
                byte_val = 0
                for bit in range(8):
                    y_out = page * 8 + bit
                    if y_out < target_h:
                        y_src = y_out + crop_y
                        if 0 <= y_src < h:
                            if surf.get_at((x_src, y_src))[0] > 127:
                                byte_val |= (1 << bit)
                buffer[page * out_w + x_out] = byte_val
            
    return buffer, out_w, target_h

def convert_font_advanced(font_path, size_request, target_height, output_name):
    print(f"Converting {font_path} (req size {size_request}) to height {target_height}...")
    
    try:
        font = pygame.font.Font(font_path, size_request)
    except Exception as e:
        print(f"Failed: {e}")
        return

    chars = "0123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ-. "
    
    min_y, max_y, max_digit_w = scan_metrics(font, chars)
    ink_h = max_y - min_y + 1
    print(f"  Ink metrics: min_y={min_y}, max_y={max_y}, height={ink_h}, max_digit_w={max_digit_w}")
    
    # Calculate crop_y to center the ink in target_height
    start_y_offset = (target_height - ink_h) // 2
    crop_y = min_y - start_y_offset
    
    print(f"  Crop Y start: {crop_y}")

    with open(output_name, 'w', encoding='utf-8') as f:
        f.write("# Converted font (Monospace Digits)\n")
        f.write("import framebuf\n\n")
        f.write(f"HEIGHT = {target_height}\n")
        f.write("GLYPHS = {}\n\n")
        
        for char in chars:
            data, w, h = convert_char(font, char, crop_y, max_digit_w, target_height)
            if data:
                bytes_str = 'b"' + ''.join(f'\\x{b:02x}' for b in data) + '"'
                f.write(f"GLYPHS['{char}'] = {{ 'w': {w}, 'h': {h}, 'data': {bytes_str} }}\n")

def main():
    files = [f for f in os.listdir(SOURCE_DIR) if f.lower().endswith(('.ttf', '.otf'))]
    
    for filename in files:
        base = os.path.splitext(filename)[0].lower().replace('-', '_')
        path = os.path.join(SOURCE_DIR, filename)
        
        # 32px version (Big) - Source 52, Target 32
        convert_font_advanced(path, 52, 32, os.path.join(OUTPUT_DIR, f"{base}_32.py"))
        
        # 16px version (Small) - Source 20, Target 16
        convert_font_advanced(path, 20, 16, os.path.join(OUTPUT_DIR, f"{base}_16.py"))

if __name__ == "__main__":
    main()

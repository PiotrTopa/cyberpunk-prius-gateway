import mmap
import time
import sys

WIDTH = 480
HEIGHT = 240
BPP = 4
STRIDE = WIDTH * BPP
TOTAL_SIZE = STRIDE * HEIGHT

# Colors in BGRA
BLACK   = b'\x00\x00\x00\xff'
WHITE   = b'\xff\xff\xff\xff'
RED     = b'\x00\x00\xff\xff'
GREEN   = b'\x00\xff\x00\xff'
BLUE    = b'\xff\x00\x00\xff'
YELLOW  = b'\x00\xff\xff\xff'
CYAN    = b'\xff\xff\x00\xff'
MAGENTA = b'\xff\x00\xff\xff'
DARK    = b'\x14\x14\x14\xff'

buf = bytearray(TOTAL_SIZE)

def set_pixel(x, y, color):
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        offset = (y * WIDTH + x) * BPP
        buf[offset:offset+4] = color

# Top half (y = 0 .. 119): 6 Vertical Color Bars (each 80 px wide)
# Bar 0 (0..79): White
# Bar 1 (80..159): Yellow
# Bar 2 (160..239): Cyan
# Bar 3 (240..319): Green
# Bar 4 (320..399): Magenta
# Bar 5 (400..479): Red
bars = [
    (0, 80, WHITE),
    (80, 160, YELLOW),
    (160, 240, CYAN),
    (240, 320, GREEN),
    (320, 400, MAGENTA),
    (400, 480, RED),
]
for x_start, x_end, col in bars:
    for y in range(0, 120):
        for x in range(x_start, x_end):
            set_pixel(x, y, col)

# Bottom half (y = 120 .. 239):
# Dark background with a wide 40px center White column (x = 220 .. 260)
for y in range(120, HEIGHT):
    for x in range(WIDTH):
        set_pixel(x, y, DARK)

for y in range(120, HEIGHT):
    for x in range(220, 260):
        set_pixel(x, y, WHITE)

# Three Green horizontal lines across full screen at y=60, 120, 180 (3px thick)
for y_center in [60, 120, 180]:
    for dy in [-1, 0, 1]:
        y_val = y_center + dy
        if 0 <= y_val < HEIGHT:
            for x in range(WIDTH):
                set_pixel(x, y_val, GREEN)

# 2px Red border around the screen
for x in range(WIDTH):
    set_pixel(x, 0, RED)
    set_pixel(x, 1, RED)
    set_pixel(x, HEIGHT - 2, RED)
    set_pixel(x, HEIGHT - 1, RED)
for y in range(HEIGHT):
    set_pixel(0, y, RED)
    set_pixel(1, y, RED)
    set_pixel(WIDTH - 2, y, RED)
    set_pixel(WIDTH - 1, y, RED)

with open('/dev/fb0', 'r+b') as fb:
    mm = mmap.mmap(fb.fileno(), TOTAL_SIZE, mmap.MAP_SHARED, mmap.PROT_WRITE)
    print("Pattern loop running on /dev/fb0...")
    sys.stdout.flush()
    while True:
        mm.seek(0)
        mm.write(buf)
        time.sleep(0.5)

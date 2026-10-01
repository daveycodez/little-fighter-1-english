#!/usr/bin/env python3
"""Preserve Firzen's original 50x50 indexed drawing; translate and paint neck only."""
from pathlib import Path
import json
import re
import sys
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'export'))
import render_character_preview as render
PALETTE = render.load_palette(ROOT)
SOURCE = ROOT / 'art/firzen/portrait/firzen-portrait-exact-start-native.png'
source = Image.open(SOURCE)
assert source.mode == 'P' and source.size == (50, 50)
assert source.getpalette() == PALETTE
SHIFT = 5
# Integer translation only. The existing top-edge hair is clipped by the canvas.
translated = render.indexed([7] * 2500, (50, 50), PALETTE)
translated.paste(source.crop((0, SHIFT, 50, 50)), (0, 0))
portrait = translated.copy()
# Only cells below the original jaw slope are painted. Each tuple is the
# inclusive visible neck interior; existing jaw pixels remain untouched.
interiors = {
    40: (34, 41), 41: (32, 42), 42: (29, 42),
    43: (27, 42), 44: (24, 44),
    45: (25, 44), 46: (25, 44), 47: (26, 44),
    48: (26, 44), 49: (27, 44),
}
painted = set()
def put(x, y, index):
    portrait.putpixel((x, y), index)
    painted.add((x, y))
# Under-jaw shadow uses the original darker skin; the rear neck has the
# original middle skin shade. No clothing or new facial marks are added.
for y, (left, right) in interiors.items():
    shade_end = {40: 36, 41: 36, 42: 35, 43: 35, 44: 34,
                 45: 34, 46: 33, 47: 33, 48: 32, 49: 32}[y]
    for x in range(left, right + 1):
        put(x, y, 81 if x <= shade_end or x >= 43 else 82)
# The isolated dark red cell below the chin is an extraction artifact, not
# pupil art; close this one neckline cell with the same black as the contour.
put(23, 44, 10)
# Front neck is set behind the chin and remains 19-21 pixels wide; it never
# replaces the original sloping jaw with a narrow vertical stem.
for y, x in {45: 24, 46: 24, 47: 25, 48: 25, 49: 26}.items():
    put(x, y, 10)
for y in range(45, 50):
    put(45, y, 10)
# One-pixel tendon, following the angled original LF1 neck-line convention.
for y, x in {40: 35, 41: 35, 42: 34, 43: 34, 44: 33,
             45: 33, 46: 32, 47: 32, 48: 31, 49: 31}.items():
    put(x, y, 10)
portrait.info['transparency'] = 0
portrait.save(OUT / 'firzen-portrait.png')
portrait.resize((200, 200), Image.Resampling.NEAREST).save(OUT / 'firzen-portrait-4x.png')
portrait.resize((500, 500), Image.Resampling.NEAREST).save(OUT / 'firzen-portrait-10x.png')
# Verify unchanged facial pixels, hair, and native palette, independent of
# the paint commands, by comparing the completed image to the translation.
changes = [(x, y) for y in range(50) for x in range(50)
           if portrait.getpixel((x, y)) != translated.getpixel((x, y))]
assert all((x, y) in painted for x, y in changes)
assert all(y >= 40 for x, y in changes)
assert all(portrait.getpixel((x, y)) == source.getpixel((x, y + SHIFT))
           for y in range(40) for x in range(50))
assert portrait.getpalette() == PALETTE
assert set(portrait.get_flattened_data()) <= {7, 10, 14, 15, 31, 34, 81, 82, 83, 97, 98}
for y in range(45, 50):
    assert all(portrait.getpixel((x, y)) in {7, 10, 81, 82} for x in range(50))
# Inspect both known pupil interiors after integer translation.
pupils = [(12, 27), (13, 27), (14, 27), (12, 28), (13, 28), (14, 28),
          (13, 29), (14, 29), (25, 27), (26, 27),
          (24, 28), (25, 28), (26, 28), (27, 28),
          (24, 29), (25, 29), (26, 29), (27, 29), (25, 30), (26, 30)]
assert all(portrait.getpixel((x, y - SHIFT)) in {31, 34} for x, y in pupils)
# Parse actual DATA.DAT face locations instead of guessing atlas tiles.
text = (ROOT / 'SYS/DATA.DAT').read_text(encoding='ascii')
sheet = render.read_grh(ROOT / 'SYS/FACE.GRH')
sheet.putpalette(PALETTE)
refs = []
locations = {}
for name in ('Firen', 'Freeze', 'Julian'):
    block = re.search(r'^\d+\.\s*' + name + r'\s*\n(.*?)(?=^\d+\.|^E$)', text, re.M | re.S).group(1)
    col, row = map(int, re.search(r'Face:\s*(\d+)\s+(\d+)', block).groups())
    locations[name] = [col, row]
    refs.append((name, sheet.crop(((col-1)*50, (row-1)*50, col*50, row*50))))
comparison = Image.new('RGB', (1100, 244), (235, 233, 229))
draw = ImageDraw.Draw(comparison)
for i, (name, image) in enumerate([('Original attached face', source), ('5px up + bare neck', portrait), *refs]):
    comparison.paste(image.convert('RGB').resize((200, 200), Image.Resampling.NEAREST), (10+i*220, 10))
    draw.text((10+i*220, 218), name, fill=(30, 30, 30))
comparison.save(OUT / 'firzen-portrait-comparison-4x.png')
report = {
    'source': str(SOURCE), 'size': [50, 50], 'translation_pixels': [0, -5],
    'resized': False, 'palette_exact_SYS_PAL': True,
    'indices': sorted(set(portrait.get_flattened_data())),
    'red_pupil_indices': [31, 34], 'hair_indices': [97, 98],
    'chin_row_zero_based': 44, 'neck_rows_below_chin': 5,
    'neck_width_including_contours_rows_45_to_49': [22, 22, 21, 21, 20],
    'paint_bounds_inclusive': [min(x for x,y in changes), min(y for x,y in changes),
                               max(x for x,y in changes), max(y for x,y in changes)],
    'pixels_changed_after_translation': len(changes),
    'unchanged_face_hair_eyes_brows_mouth': True,
    'jaw_contour_preserved': 'Original jaw untouched; one isolated red neckline cell closed at x23 y44.',
    'reference_face_slots_1_based': locations,
    'output': str(OUT / 'firzen-portrait.png'),
    'preview_4x': str(OUT / 'firzen-portrait-4x.png'),
    'comparison': str(OUT / 'firzen-portrait-comparison-4x.png'),
}
(OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))

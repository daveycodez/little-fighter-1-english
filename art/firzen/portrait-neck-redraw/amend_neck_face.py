#!/usr/bin/env python3
"""Amend the existing approved V: widen front neck and restore source facial ink."""
from pathlib import Path
import json
import sys
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'export'))
import render_character_preview as render
palette = render.load_palette(ROOT)
path = OUT / 'firzen-portrait.png'
before_path = OUT / 'before.PNG'
if not before_path.exists():
    before_path.write_bytes(path.read_bytes())
before = Image.open(before_path)
portrait = before.copy()
assert before.size == (50, 50) and before.mode == 'P'
assert before.getpalette() == palette
v = {40: 35, 41: 35, 42: 34, 43: 34, 44: 33,
     45: 33, 46: 32, 47: 32, 48: 31, 49: 31}
v_before = {(x, y): before.getpixel((x, y)) for y, x in v.items()}
old_front = {45: 24, 46: 24, 47: 25, 48: 25, 49: 26}
new_front = {45: 21, 46: 21, 47: 22, 48: 22, 49: 23}
# Connect beneath the original chin's black cells at y44, x18..23.
# Move only the front neck outline left three pixels, filling the gap and
# replacing the superseded outline with the original dark bare-skin shade.
for y, x in new_front.items():
    portrait.putpixel((x, y), 10)
    for fill_x in range(x + 1, old_front[y] + 1):
        portrait.putpixel((fill_x, y), 81)
# Actual attached-image ink covers x17..24 predominantly in source row39
# (44% black coverage versus 24% in row40), becoming y34 after the existing
# five-pixel shift. Restore it as one neutral horizontal native-pixel line.
mouth = [(x, 34) for x in range(17, 25)]
# These source nose cells have 54%,33%,32%,36% original black coverage;
# the original conversion lost them. Existing nose pixels stay in place.
nose_restore = [(15, 27), (13, 29), (14, 30), (14, 31)]
for xy in mouth + nose_restore:
    portrait.putpixel(xy, 10)
assert all(portrait.getpixel(xy) == value for xy, value in v_before.items())
changed = [(x, y) for y in range(50) for x in range(50)
           if before.getpixel((x, y)) != portrait.getpixel((x, y))]
expected = set(mouth + nose_restore)
expected.update((x, y) for y in new_front for x in range(new_front[y], old_front[y] + 1))
assert set(changed) == expected
assert all(portrait.getpixel((new_front[y], y)) == 10 for y in range(45, 50))
assert before.getpixel((new_front[45], 44)) == 10
assert all(abs(new_front[y] - new_front[y+1]) <= 1 for y in range(45, 49))
assert portrait.getpalette() == palette
assert set(portrait.get_flattened_data()) <= {7, 10, 14, 15, 31, 34, 81, 82, 83, 97, 98}
portrait.info['transparency'] = 0
portrait.save(path)
portrait.resize((200, 200), Image.Resampling.NEAREST).save(OUT / 'firzen-portrait-4x.png')
portrait.resize((500, 500), Image.Resampling.NEAREST).save(OUT / 'firzen-portrait-10x.png')
before.resize((200, 200), Image.Resampling.NEAREST).save(OUT / 'before-4x.png')
comparison = Image.new('RGB', (440, 244), (235, 233, 229))
d = ImageDraw.Draw(comparison)
for i, (name, im) in enumerate([('Before', before), ('Wider neck + source ink', portrait)]):
    comparison.paste(im.convert('RGB').resize((200, 200), Image.Resampling.NEAREST), (10+i*220, 10))
    d.text((10+i*220, 218), name, fill=(30, 30, 30))
comparison.save(OUT / 'neck-mouth-before-after-4x.png')
# Rebuild native reference comparison with final candidate.
base = Image.open(ROOT / 'art/firzen/portrait/firzen-portrait-exact-start-native.png')
sheet = render.read_grh(ROOT / 'SYS/FACE.GRH'); sheet.putpalette(palette)
comparison = Image.new('RGB', (1100, 244), (235, 233, 229)); d = ImageDraw.Draw(comparison)
refs = [('Original attached face', base), ('Wider neck + restored ink', portrait),
        ('Firen', sheet.crop((100,50,150,100))), ('Freeze', sheet.crop((200,0,250,50))),
        ('Julian', sheet.crop((250,0,300,50)))]
for i, (name, im) in enumerate(refs):
    comparison.paste(im.convert('RGB').resize((200,200), Image.Resampling.NEAREST), (10+i*220,10))
    d.text((10+i*220,218), name, fill=(30,30,30))
comparison.save(OUT / 'firzen-portrait-comparison-4x.png')
nose_box = [(x,y) for y in range(27,33) for x in range(13,18)]
report = {
    'source': str(before_path), 'target': str(path), 'native_size': [50,50],
    'existing_translation_preserved': [0,-5], 'further_resizing': False,
    'neck_widened_left_pixels': 3,
    'front_neck_black_coordinates': [[x,y] for y,x in new_front.items()],
    'front_neck_connected_to_chin': True, 'front_neck_connected_to_bottom': True,
    'neck_width_including_contours_rows_45_to_49': [25,25,24,24,23],
    'V_tendon_pixels_unchanged': True,
    'mouth_black_coordinates': [list(xy) for xy in mouth],
    'mouth_black_pixel_count': len(mouth), 'mouth_previous_black_pixel_count': 0,
    'nose_restored_black_coordinates': [list(xy) for xy in nose_restore],
    'nose_black_pixel_count_after': sum(portrait.getpixel(xy)==10 for xy in nose_box),
    'nose_black_pixel_count_before': sum(before.getpixel(xy)==10 for xy in nose_box),
    'changed_pixels_count': len(changed), 'changed_coordinates': [list(xy) for xy in changed],
    'exact_SYS_PAL': True, 'all_other_pixels_unchanged': True,
    'preview': str(OUT / 'firzen-portrait-4x.png'),
}
(OUT / 'amendment-validation.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='changed_coordinates'}, indent=2))

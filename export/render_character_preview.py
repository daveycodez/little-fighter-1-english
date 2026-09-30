#!/usr/bin/env python3
"""Render standing and shared casting previews from LF1's original indexed assets.

Original character:
  python3 export/render_character_preview.py --name Julian --compare Davis \
    --output art/julian-standing.png

Custom character:
  python3 export/render_character_preview.py --name Firzen \
    --head art/firzen/firzen-head-gameplay-v45.png \
    --skin 83,81 --shirt 76,78 --trousers 133,135 \
    --compare Davis --output art/previews/firzen-standing.png

Requires Pillow. This is an offline asset renderer, not a game patch.
The game uses 25x25 ACT1 cells and a separate 17x12 HEAD crop. PAL triples
are installed starting at VGA index 1 (FIGHT.EXE file offset 0x6707).
Standing frames 1-5 overlay the head at (0,0). Hurt/fall frames 14-18 and
shared casting frames 35/43 use baked-in hair at source index 160 and skip
the head overlay, matching
FIGHT.EXE's head-position initialization and draw gate. Other poses remain
unsupported until their per-frame rendering rules are verified.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

HEADER_SIZE = 300
HEAD_SIZE = (17, 12)
BODY_SIZE = (25, 25)
SUPPORTED_FRAMES = (1, 2, 3, 4, 5, 14, 15, 16, 17, 18, 35, 43)
BAKED_HEAD_FRAMES = (14, 15, 16, 17, 18, 35, 43)


def load_palette(root: Path) -> list[int]:
    raw = (root / 'SYS' / 'PAL').read_bytes()
    if len(raw) != 768:
        raise ValueError('SYS/PAL must contain 256 RGB triples.')
    # The loader writes all 768 bytes with DAC start index 1, wraps to 0,
    # then explicitly sets index 0 black. Index 0 is also sprite transparency.
    colors = [0, 0, 0]
    for index in range(1, 256):
        colors.extend(channel * 4 for channel in raw[(index-1)*3:index*3])
    return colors


def read_grh(path: Path) -> Image.Image:
    raw = path.read_bytes()
    if len(raw) < HEADER_SIZE:
        raise ValueError(f'{path}: incomplete GRH header.')
    width, height = struct.unpack_from('>HH', raw)
    if not width or not height or len(raw) != HEADER_SIZE + width * height:
        raise ValueError(f'{path}: GRH dimensions do not match payload.')
    return Image.frombytes('P', (width, height), raw[HEADER_SIZE:])


def indexed(pixels: list[int], size: tuple[int, int], palette: list[int]) -> Image.Image:
    image = Image.new('P', size)
    image.putpalette(palette)
    image.putdata(pixels)
    image.info['transparency'] = 0
    return image


def crop_pixels(image: Image.Image, box: tuple[int, int, int, int]) -> list[int]:
    if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
        raise ValueError('Requested sprite is outside the source atlas.')
    return list(image.crop(box).get_flattened_data())


def original_characters(root: Path) -> dict[str, dict]:
    text = (root / 'SYS' / 'DATA.DAT').read_text(encoding='ascii')
    starts = list(re.finditer(r'^\d+\.\s*([^\r\n]+)', text, re.M))
    records = {}
    hair_table = [int(v) for v in re.search(r'\nE\s*\n([^\n]+)', text).group(1).split()]
    for i, match in enumerate(starts):
        block = text[match.end():starts[i+1].start() if i+1 < len(starts) else len(text)]
        name = match.group(1).strip()
        record = {'name': name}
        record['head_id'] = int(re.search(r'Head:\s*(\d+)', block).group(1))
        record['hair'] = hair_table[record['head_id']-1]
        for field, key in [('Skn', 'skin'), ('Sht', 'shirt'), ('Trs', 'trousers')]:
            pair = re.search(rf'{field}:\s*(\d+)\s+(\d+)', block)
            record[key] = [int(pair.group(1)), int(pair.group(2))]
        records[name.casefold()] = record
    return records


def nearest_color(rgb: tuple[int, int, int], palette: list[int]) -> int:
    # Fixed colors 1-150; 151+ are the game's dynamic per-fighter banks.
    # Retain a visibly colored source pixel's hue when its muted RGB would
    # otherwise map to gray. This is format conversion, not pixel repainting.
    source_hue, source_sat, _ = colorsys.rgb_to_hsv(*(v/255 for v in rgb))
    candidates = list(range(1, 151))
    if source_sat >= 0.25 and max(rgb) >= 40:
        colored = []
        for i in candidates:
            target = tuple(palette[i*3:i*3+3])
            hue, saturation, _ = colorsys.rgb_to_hsv(*(v/255 for v in target))
            hue_distance = min(abs(hue-source_hue), 1-abs(hue-source_hue))
            if saturation >= 0.2 and hue_distance <= 0.10:
                colored.append(i)
        if colored:
            candidates = colored
    return min(candidates, key=lambda i: sum(
        (palette[i*3+channel] - rgb[channel])**2 for channel in range(3)))


def validate_head_indices(pixels: list[int]) -> list[int]:
    invalid = sorted({v for v in pixels if not 0 <= v <= 150})
    if invalid:
        raise ValueError(f'Custom head uses non-fixed palette indices {invalid}; '
                         'indices 151+ can overlap LF1 per-fighter color banks.')
    return pixels


def custom_head(path: Path, palette: list[int], grid_path: Path | None = None) -> tuple[list[int], dict]:
    if path.suffix.casefold() == '.grh':
        image = read_grh(path)
        if image.size != HEAD_SIZE:
            raise ValueError('Native head GRH must be exactly 17x12.')
        return validate_head_indices(list(image.get_flattened_data())), {'conversion': 'native GRH indices preserved'}
    image = Image.open(path)
    if image.mode == 'P' and image.size == HEAD_SIZE:
        # Preserve native LF1 index semantics rather than requantizing.
        if image.getpalette()[:768] != palette:
            # Index 0 RGB is irrelevant because it is transparent.
            if image.getpalette()[3:768] != palette[3:768]:
                raise ValueError('Indexed head palette differs from LF1. Supply RGBA art to convert it.')
        if image.info.get('transparency') != 0:
            raise ValueError('Indexed native head must use transparency index 0.')
        return validate_head_indices(list(image.get_flattened_data())), {'conversion': 'native PNG indices preserved'}
    image = image.convert('RGBA')
    alpha = image.getchannel('A').point(lambda value: 255 if value >= 128 else 0)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError('Head image is empty.')
    if alpha.getextrema() == (255, 255):
        raise ValueError('Head artwork needs a transparent background.')
    conversion = {'conversion': 'native RGBA grid; hue-preserving LF1 palette conversion',
                  'face_substitution': False, 'geometry_rescaling': False}
    if image.size != HEAD_SIZE:
        if grid_path is None:
            raise ValueError('Head must be a native 17x12 tile. Oversized artwork requires '
                             '--head-grid with explicit source cells and target rows/columns; '
                             'automatic resizing would damage facial features.')
        grid = json.loads(grid_path.read_text())
        xs, ys = grid['x_edges'], grid['y_edges']
        columns, rows = grid['columns'], grid['rows']
        if len(columns) != 17 or len(rows) != 12:
            raise ValueError('Head grid must map exactly 17 columns and 12 rows.')
        if (len(xs) < 2 or len(ys) < 2 or xs[0] < 0 or ys[0] < 0
                or xs[-1] > image.width or ys[-1] > image.height
                or any(a >= b for a, b in zip(xs, xs[1:]))
                or any(a >= b for a, b in zip(ys, ys[1:]))):
            raise ValueError('Source grid edges are invalid or outside the artwork.')
        if any(c is not None and (not isinstance(c, int) or not 0 <= c < len(xs)-1) for c in columns):
            raise ValueError('Source column index is out of bounds.')
        if any(r is not None and (not isinstance(r, int) or not 0 <= r < len(ys)-1) for r in rows):
            raise ValueError('Source row index is out of bounds.')
        cells = []
        for sy in range(len(ys)-1):
            line = []
            for sx in range(len(xs)-1):
                x0, x1, y0, y1 = xs[sx], xs[sx+1], ys[sy], ys[sy+1]
                # Read each logical square once, well inside its edges.
                dx, dy = (x1-x0)//4, (y1-y0)//4
                sample = image.crop((x0+dx, y0+dy, x1-dx, y1-dy))
                line.append(tuple(int(v) for v in ImageStat.Stat(sample).median))
            cells.append(line)
        mapped = Image.new('RGBA', HEAD_SIZE)
        mapped.putdata([(0, 0, 0, 0) if sy is None or sx is None else cells[sy][sx]
                        for sy in rows for sx in columns])
        image = mapped
        conversion.update({'conversion': 'explicit logical pixel-grid extraction; hue-preserving LF1 palette conversion',
                           'grid_definition': str(grid_path.resolve()),
                           'source_grid_size': [len(xs)-1, len(ys)-1],
                           'target_columns': columns, 'target_rows': rows,
                           'adaptation': grid.get('adaptation', '')})
    pixels = [0 if a < 128 else nearest_color((r, g, b), palette)
              for r, g, b, a in image.get_flattened_data()]
    return validate_head_indices(pixels), conversion


def render_character(root: Path, palette: list[int], record: dict, frame: int,
                     head_path: Path | None = None, grid_path: Path | None = None) -> tuple[Image.Image, Image.Image, dict]:
    if frame not in SUPPORTED_FRAMES:
        raise ValueError(f'Unverified frame {frame}; supported frames: {SUPPORTED_FRAMES}.')
    source = read_grh(root / 'SYS' / 'ACT1.GRH')
    x = ((frame-1) % 12) * 26 + 1
    y = ((frame-1) // 12) * 26 + 1
    body = crop_pixels(source, (x, y, x+25, y+25))
    # DATA.DAT supplies six body colors. LOAD_DATA adds white, red, black.
    # Verified file 0x17ECA..0x17EE8: constants 15,31,10 (not 15,16,10).
    body_colors = record['skin'] + record['shirt'] + record['trousers'] + [15, 31, 10]
    remap = {151+i: value for i, value in enumerate(body_colors)}
    if frame in BAKED_HEAD_FRAMES:
        hair = record.get('hair')
        if hair is None or not 1 <= hair <= 150:
            raise ValueError('Baked-head casting frames require a fixed hair palette index.')
        # FIGHT.EXE maps source 160 to the selected head's DATA.DAT hair color.
        remap[160] = hair
    composite = [remap.get(value, value) for value in body]
    if head_path:
        head, conversion = custom_head(head_path, palette, grid_path)
    else:
        head_id = record['head_id']
        atlas = read_grh(root / 'SYS' / 'HEAD.GRH')
        hx = ((head_id-1) % 11) * 18 + 1
        hy = ((head_id-1) // 11) * 13 + 1
        head = crop_pixels(atlas, (hx, hy, hx+17, hy+12))
        conversion = {'conversion': 'original HEAD.GRH indices preserved', 'head_id': head_id}
    # Initializer sets head Y=50 for frames 12-20 and 33-43 (file 0x189D5..0x18A2F).
    # The drawing gate (file 0x19829..0x19850) skips Y>=50 and frames>60.
    head_overlay = frame not in BAKED_HEAD_FRAMES
    if head_overlay:
        for hy in range(12):
            for hx in range(17):
                value = head[hy*17+hx]
                if value:
                    composite[hy*25+hx] = value
    mismatches = (sum(composite[hy*25+hx] != head[hy*17+hx]
                      for hy in range(12) for hx in range(17) if head[hy*17+hx])
                  if head_overlay else 0)
    if mismatches:
        raise ValueError('Head/composite pixel consistency check failed.')
    metadata = {'character': record, 'frame': frame, 'body_crop': [x, y, 25, 25],
                'head_size': [17, 12], 'head_offset': [0, 0] if head_overlay else None,
                'head_overlay': head_overlay, 'transparent_index': 0,
                'head_source': str(head_path.resolve()) if head_path else 'SYS/HEAD.GRH',
                'head_conversion': conversion, 'head_pixel_mismatches': mismatches,
                'hair_recolor': {'source_index': 160, 'target_index': record['hair']} if not head_overlay else None,
                'rendering': 'offline reproduction of LF1 standing/shared casting compositing; not an in-game screenshot'}
    return indexed(composite, BODY_SIZE, palette), indexed(head, HEAD_SIZE, palette), metadata


def color_pair(value: str) -> list[int]:
    try:
        pair = [int(item) for item in value.split(',')]
    except ValueError as error:
        raise argparse.ArgumentTypeError('Use two palette indices, e.g. 83,81.') from error
    if len(pair) != 2 or any(v < 1 or v > 150 for v in pair):
        raise argparse.ArgumentTypeError('Use two fixed palette indices in 1-150.')
    return pair


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game-root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--name', required=True)
    parser.add_argument('--head', type=Path, help='Custom transparent PNG or native 17x12 GRH.')
    parser.add_argument('--head-grid', type=Path, help='Explicit logical grid mapping for oversized source art.')
    parser.add_argument('--skin', type=color_pair)
    parser.add_argument('--shirt', type=color_pair)
    parser.add_argument('--trousers', type=color_pair)
    parser.add_argument('--hair', type=int, choices=range(1, 151), help='Fixed palette index for baked-in casting hair.')
    parser.add_argument('--frame', type=int, choices=SUPPORTED_FRAMES, default=2)
    parser.add_argument('--compare', default='Davis')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    palette = load_palette(args.game_root)
    originals = original_characters(args.game_root)
    if args.name.casefold() in originals:
        record = dict(originals[args.name.casefold()])
    else:
        if not args.head or any(v is None for v in [args.skin, args.shirt, args.trousers]):
            parser.error('Custom characters need --head, --skin, --shirt, and --trousers.')
        record = {'name': args.name}
    for key in ['skin', 'shirt', 'trousers']:
        value = getattr(args, key)
        if value is not None:
            record[key] = value
    if args.hair is not None:
        record['hair'] = args.hair
    if args.compare.casefold() not in originals:
        parser.error('--compare must name an original character in DATA.DAT.')
    fighter, head, metadata = render_character(args.game_root, palette, record, args.frame, args.head, args.head_grid)
    reference_record = originals[args.compare.casefold()]
    reference, _, reference_metadata = render_character(args.game_root, palette, reference_record, args.frame)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    prefix = args.output.with_suffix('')
    native_path = prefix.with_name(prefix.name + '-native.png')
    head_path = prefix.with_name(prefix.name + '-head.png')
    grh_path = prefix.with_name(prefix.name + '-head.GRH')
    fighter.save(native_path, transparency=0)
    head.save(head_path, transparency=0)
    header = bytearray(HEADER_SIZE)
    struct.pack_into('>HH', header, 0, *HEAD_SIZE)
    grh_path.write_bytes(bytes(header) + bytes(head.get_flattened_data()))
    # Native-size comparison. Never resize body or head images.
    width, height = 140, 76
    canvas = Image.new('RGB', (width, height), (25, 29, 32))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=10)
    draw.text((width//2, 3), f'LF1 frame {args.frame}', font=font,
              fill=(236, 236, 224), anchor='mt')
    centers = (35, 105)
    for cx, label, sprite in [(centers[0], record['name'], fighter),
                              (centers[1], reference_record['name'], reference)]:
        display = sprite.convert('RGBA')
        canvas.paste(display, (cx-display.width//2, 22), display)
        draw.text((cx, 54), label.upper(), font=font,
                  fill=(236, 236, 224), anchor='mt')
    canvas.resize((width*4, height*4), Image.Resampling.NEAREST).save(args.output)
    metadata['preview_scaling'] = '4x nearest-neighbor display; native sprite and head assets unchanged'
    metadata['reference'] = reference_metadata
    metadata['outputs'] = {'comparison': str(args.output.resolve()), 'native': str(native_path.resolve()),
                           'head': str(head_path.resolve()), 'head_grh': str(grh_path.resolve())}
    prefix.with_name(prefix.name+'-render.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(f'Saved {args.output}: shared ACT1 frame {args.frame}; head overlay: {metadata["head_overlay"]}.')


if __name__ == '__main__':
    main()

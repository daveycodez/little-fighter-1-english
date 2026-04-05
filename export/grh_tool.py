#!/usr/bin/env python3
"""
GRH <-> PNG converter for Little Fighter (1995).

Usage:
  python3 grh_tool.py export <file.GRH> [output.png]   -- GRH to PNG
  python3 grh_tool.py import <file.png> [output.GRH]   -- PNG to GRH
  python3 grh_tool.py exportall                         -- export every GRH in ../SYS to PNG

Requires: Pillow (pip install Pillow)
PAL file is expected at ../SYS/PAL relative to this script, or alongside the GRH.
"""

import struct, sys
from pathlib import Path
from PIL import Image

HEADER_SIZE = 300
PAL_SCALE = 4  # VGA 6-bit -> 8-bit


def load_palette(pal_path: Path):
    data = pal_path.read_bytes()
    assert len(data) == 768, f"PAL file should be 768 bytes, got {len(data)}"
    flat = []
    for i in range(256):
        r = min(data[i * 3] * PAL_SCALE, 255)
        g = min(data[i * 3 + 1] * PAL_SCALE, 255)
        b = min(data[i * 3 + 2] * PAL_SCALE, 255)
        flat.extend([r, g, b])
    return flat


def find_pal(near: Path) -> Path:
    candidates = [near.parent / "PAL", near.parent.parent / "SYS" / "PAL", Path(__file__).parent.parent / "SYS" / "PAL"]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("Cannot find PAL file")


def grh_to_png(grh_path: Path, png_path: Path):
    raw = grh_path.read_bytes()
    w = struct.unpack_from(">H", raw, 0)[0]
    h = struct.unpack_from(">H", raw, 2)[0]
    expected = HEADER_SIZE + w * h
    assert len(raw) == expected, f"Size mismatch: {len(raw)} != {expected} ({w}x{h})"

    pal = load_palette(find_pal(grh_path))
    img = Image.new("P", (w, h))
    img.putpalette(pal)
    img.putdata(list(raw[HEADER_SIZE:]))
    img.convert("RGB").save(png_path)
    print(f"{grh_path.name} -> {png_path.name}  ({w}x{h})")


def png_to_grh(png_path: Path, grh_path: Path):
    pal_flat = load_palette(find_pal(grh_path if grh_path.exists() else png_path))

    pal_rgb = [(pal_flat[i * 3], pal_flat[i * 3 + 1], pal_flat[i * 3 + 2]) for i in range(256)]
    rgb_to_idx = {c: i for i, c in enumerate(pal_rgb)}

    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    pixels = bytearray(w * h)

    for y in range(h):
        for x in range(w):
            px = img.getpixel((x, y))
            idx = rgb_to_idx.get(px)
            if idx is None:
                best, best_d = 0, 999999
                for i, (pr, pg, pb) in enumerate(pal_rgb):
                    d = (px[0] - pr) ** 2 + (px[1] - pg) ** 2 + (px[2] - pb) ** 2
                    if d < best_d:
                        best, best_d = i, d
                        if d == 0:
                            break
                idx = best
            pixels[y * w + x] = idx

    header = bytearray(HEADER_SIZE)
    struct.pack_into(">HH", header, 0, w, h)
    grh_path.write_bytes(bytes(header) + bytes(pixels))
    print(f"{png_path.name} -> {grh_path.name}  ({w}x{h}, {len(header) + len(pixels)} bytes)")


def export_all():
    sys_dir = Path(__file__).parent.parent / "SYS"
    out_dir = Path(__file__).parent
    for grh in sorted(sys_dir.glob("*.GRH")):
        try:
            grh_to_png(grh, out_dir / (grh.stem + ".png"))
        except Exception as e:
            print(f"SKIP {grh.name}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "export":
        src = Path(sys.argv[2])
        dst = Path(sys.argv[3]) if len(sys.argv) > 3 else src.with_suffix(".png")
        grh_to_png(src, dst)

    elif cmd == "import":
        src = Path(sys.argv[2])
        dst = Path(sys.argv[3]) if len(sys.argv) > 3 else src.with_suffix(".GRH")
        png_to_grh(src, dst)

    elif cmd == "exportall":
        export_all()

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

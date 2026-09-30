#!/usr/bin/env python3
"""Preview native LF1 heads at exactly 4x, preserving source pixels.

  python3 export/render_head_preview.py \
    --head art/firzen/firzen-head-gameplay-v45.png \
    --output art/previews/firzen-head-4x.png --check-palette

Add --checker for a transparency checkerboard.
Add --compare Julian --name Firzen for a labeled original-head comparison. PNG pixels are copied without
recoloring. GRH input uses LF1's palette and transparency index 0.
"""
from pathlib import Path
import argparse
from PIL import Image, ImageDraw, ImageFont
from render_character_preview import HEAD_SIZE, load_palette, read_grh, original_characters, crop_pixels, indexed


def validate_palette(image, palette):
    supported={tuple(palette[i*3:i*3+3]) for i in range(1,151)}
    pixels=list(image.get_flattened_data())
    invalid=sorted({tuple(p[:3]) for p in pixels if p[3] and tuple(p[:3]) not in supported})
    alpha=sorted({p[3] for p in pixels})
    if invalid or any(a not in (0,255) for a in alpha):
        raise ValueError(f'Unsupported colors: {invalid}; alpha values: {alpha}')
    return len({tuple(p[:3]) for p in pixels if p[3]})


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--head',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--game-root',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--checker',action='store_true')
    parser.add_argument('--compare',help='Original LF1 character head to show on the left.')
    parser.add_argument('--name',help='Label for the supplied head in a comparison.')
    parser.add_argument('--check-palette',action='store_true')
    args=parser.parse_args()
    palette=load_palette(args.game_root)
    if args.head.suffix.lower()=='.grh':
        image=read_grh(args.head)
        image.putpalette(palette)
        image.info['transparency']=0
    else:
        image=Image.open(args.head)
    if image.size!=HEAD_SIZE:
        parser.error(f'Expected native {HEAD_SIZE} head, got {image.size}; no fitting or resizing is performed.')
    image=image.convert('RGBA')
    if args.check_palette:
        count=validate_palette(image,palette)
        print(f'Palette valid: {count} opaque colors; alpha only 0/255.')
    def display_head(native):
        if args.checker:
            backdrop=Image.new('RGB',HEAD_SIZE)
            backdrop.putdata([tuple(palette[(12 if (x//3+y//3)%2 else 13)*3:((12 if (x//3+y//3)%2 else 13)*3)+3])
                              for y in range(HEAD_SIZE[1]) for x in range(HEAD_SIZE[0])])
            backdrop.paste(native,(0,0),native)
            native=backdrop
        return native.resize((HEAD_SIZE[0]*4,HEAD_SIZE[1]*4),Image.Resampling.NEAREST)
    result=display_head(image)
    if args.compare:
        records=original_characters(args.game_root)
        record=records.get(args.compare.casefold())
        if record is None:
            parser.error('--compare must name an original LF1 character.')
        head_id=record['head_id']
        x=((head_id-1)%11)*18+1
        y=((head_id-1)//11)*13+1
        atlas=read_grh(args.game_root/'SYS/HEAD.GRH')
        reference=indexed(crop_pixels(atlas,(x,y,x+17,y+12)),HEAD_SIZE,palette).convert('RGBA')
        reference=display_head(reference)
        canvas=Image.new('RGBA',(168,80),(30,30,30,255))
        canvas.alpha_composite(reference.convert('RGBA'),(8,8))
        canvas.alpha_composite(result.convert('RGBA'),(92,8))
        draw=ImageDraw.Draw(canvas)
        font=ImageFont.load_default(size=12)
        draw.text((42,63),record['name'],font=font,fill=(236,236,224),anchor='mt')
        draw.text((126,63),args.name or args.head.stem,font=font,fill=(236,236,224),anchor='mt')
        result=canvas
    args.output.parent.mkdir(parents=True,exist_ok=True)
    result.save(args.output)
    print(f'Saved {args.output} at exact4x; source untouched.')


if __name__=='__main__':
    main()

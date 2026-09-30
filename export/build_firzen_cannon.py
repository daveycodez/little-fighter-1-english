#!/usr/bin/env python3
"""Build an LF1-palette Cannon and mirror its own trail for continuing shots.

The original lead's geometry is preserved. Its LF2 RGB swatches are converted
explicitly to LF1's fixed palette. The continuation copies columns 0..13,
rows 3..11, followed by a center column and the horizontally mirrored copy.
The three small orange bars at the join are replaced by white core pixels.
No scaling or edge extension is used.
"""
from pathlib import Path
import hashlib
import json
from PIL import Image,ImageDraw,ImageFont
from render_character_preview import load_palette,indexed


def main():
    root=Path(__file__).resolve().parent.parent
    palette=load_palette(root)
    source=root/'art/firzen/firzen-ball-v1.png'
    original=Image.open(source).convert('RGBA')
    # LF1 lacks a pale lemon/cream swatch: both light core colors become white.
    # Use vivid yellow rather than the RGB-nearest peach skin tone for lemon.
    mapping={(255,255,255):15,(255,255,197):15,(255,255,84):65,
             (255,191,33):67,(255,159,1):68}
    lead_pixels=[0 if p[3]==0 else mapping[p[:3]] for p in original.get_flattened_data()]
    lead=indexed(lead_pixels,original.size,palette)
    assert lead.size==(29,15)
    assert [v!=0 for v in lead_pixels]==[p[3]!=0 for p in original.get_flattened_data()]
    # Preserve the source trail's nine rows and thin, staggered edges exactly.
    columns=list(range(14))+[13]+list(reversed(range(14)))
    rows=list(range(3,12))
    segment_pixels=[lead.getpixel((x,y)) for y in rows for x in columns]
    for y in (2,4,6):
        for x in (13,14,15):
            assert segment_pixels[y*29+x]==67
            segment_pixels[y*29+x]=15
    segment=indexed(segment_pixels,(29,9),palette)
    assert segment.width==lead.width
    assert segment.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()==segment.tobytes()
    assert set(segment_pixels)==set(lead_pixels)=={0,15,65,67,68}
    for output_name,image in [('firzen-ball-v2.png',lead),('firzen-cannon-segment-v4.png',segment)]:
        path=root/'art/firzen'/output_name
        image.save(path,transparency=0)
        with Image.open(path) as saved:
            assert saved.mode=='P' and saved.info['transparency']==0
            assert saved.getpalette()==palette
            assert saved.tobytes()==image.tobytes()
    meta={'method':'Exact native source pixels and horizontal mirroring',
          'original_lead':str(source),'original_lead_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'lead':'firzen-ball-v2.png','lead_size':[29,15],
          'segment':'firzen-cannon-segment-v4.png','segment_size':[29,9],
          'segment_source_columns':columns,'segment_source_rows':rows,
          'removed_join_bars':{'columns':[13,14,15],'rows':[2,4,6],'replacement_index':15},
          'extra_edge_extension':False,'geometry_scaling':False,
          'palette_source':'SYS/PAL, loaded starting at VGA index 1',
          'palette_validated':True,'indices':[15,65,67,68],
          'color_conversion':[{'source_rgb':list(rgb),'palette_index':i,'lf1_rgb':palette[i*3:i*3+3]}
                              for rgb,i in mapping.items()],
          'preview_scale':4}
    for name in ['firzen-ball-v2.json','firzen-cannon-segment-v4.json']:
        (root/'art/firzen'/name).write_text(json.dumps(meta,indent=2)+'\n')
    board=Image.new('RGB',(272,100),(237,235,231));draw=ImageDraw.Draw(board)
    font=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',12)
    for i,(label,sprite) in enumerate([('Leading shot',lead),('Mirrored trail',segment)]):
        field=Image.new('RGBA',(29,15))
        for y in range(15):
            for x in range(29):
                field.putpixel((x,y),(96,96,96,255) if (x//3+y//3)%2 else (148,148,148,255))
        field.alpha_composite(sprite.convert('RGBA'),(0,7-sprite.height//2))
        board.paste(field.resize((116,60),Image.Resampling.NEAREST).convert('RGB'),(10+i*136,8))
        draw.text((68+i*136,83),label,font=font,anchor='mm',fill=(24,24,24))
    board.save(root/'art/previews/firzen-cannon-both-projectiles-v4-lf1-4x.png')
    print('Saved lead v2 + segment v4: exact LF1 palette indices 15/65/67/68; 29px wide; mirrored source trail.')


if __name__=='__main__':
    main()

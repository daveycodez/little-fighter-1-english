#!/usr/bin/env python3
"""Convert original generated Firzen artwork to a native LF1 portrait.
The source is a completely new drawing; native faces are never pasted into it.
The user explicitly requested programmatic pixel cleanup after image generation.
"""
from pathlib import Path
import sys,json
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'export'))
import render_character_preview as render
palette=render.load_palette(ROOT)
source=Image.open(ROOT/'art/firzen/portrait/firzen-portrait-imagegen-source.png').convert('RGB')
# Native-size conversion of generated art, preserving crisp ink with nearest
# neighbour sampling. Previews enlarge these final pixels by exactly four.
native=source.resize((50,50),Image.Resampling.NEAREST)
allowed=[7,10,14,15,31,34,66,77,81,82,83,97,98]
colors={i:tuple(palette[i*3:i*3+3]) for i in allowed}
def nearest(rgb):
    # Preserve deliberate black ink and separate each material's shade family.
    r,g,b=rgb
    if max(rgb)<55:return 10
    if g>r*1.3 and g>b*1.1:
        candidates=[97,98]
    elif r>80 and g<r*0.25 and b<r*0.25:
        candidates=[31,34]
    elif b>r*1.5 and b>g*1.15:
        candidates=[7]
    elif r>g*1.09 and g>b*1.06 and g>70 and b>50:
        candidates=[81,82,83]
    elif r>150 and g>90 and b<70:
        candidates=[66,77]
    elif max(rgb)-min(rgb)<45:
        candidates=[10,14,15]
    else:candidates=allowed
    return min(candidates,key=lambda i:sum((rgb[c]-colors[i][c])**2 for c in range(3)))
indices=[nearest(p) for p in native.get_flattened_data()]
# Preserve subcell ink coverage so downsampling cannot break thin contours.
ink=Image.new('L',source.size)
ink.putdata([255 if max(p)<55 else 0 for p in source.get_flattened_data()])
ink=ink.resize((50,50),Image.Resampling.BOX)
indices=[10 if covered>=96 else color for color,covered in zip(indices,ink.get_flattened_data())]
portrait=render.indexed(indices,(50,50),palette)
# Restore the user's preferred original illustration: no global pixel shift,
# no broad replacement face or neck polygons, no eyebrow/hair repainting.
# Only iris planes and the last few chin/neck contour cells need native cleanup.
near={27:{25:34,26:34},28:{24:34,25:31,26:31,27:34},29:{24:34,25:31,26:31,27:34},30:{25:34,26:34}}
far={27:{12:34,13:31,14:34},28:{12:34,13:31,14:34},29:{13:34,14:34}}
for shape in [near,far]:
    for y,row in shape.items():
        for x,color in row.items():portrait.putpixel((x,y),color)
# Close the chin two rows inside the lower canvas edge. Preserve generated
# cheek/neck shading and redraw only the small formerly cropped contour.
d=ImageDraw.Draw(portrait)
left={43:16,44:17,45:18,46:28,47:28,48:27,49:27}
for y,boundary in left.items():
    for x in range(boundary):
        if portrait.getpixel((x,y)) not in [97,98]:portrait.putpixel((x,y),7)
# Remove only the superseded lower jaw's black stroke inside the bare neck.
for y in range(43,50):
    for x in range(25,40):
        if portrait.getpixel((x,y))==10:portrait.putpixel((x,y),81)
d.polygon([(15,42),(26,42),(24,44),(22,45),(18,45),(17,44),(16,43)],fill=83)
d.line([(15,42),(16,43),(17,44),(18,45),(23,45),(27,44),(30,43),(33,42),(36,41)],fill=10,width=1)
for x in range(24,28):portrait.putpixel((x,45),7)
# Preserve the generated bare neck's shade planes and its rear contour.
d.line([(29,44),(28,46),(27,48),(27,49)],fill=10,width=1)
for y in range(40,50):
    for x in range(50):
        if portrait.getpixel((x,y)) in [14,15]:
            portrait.putpixel((x,y),82 if 25<=x<=43 else 7)
indices=list(portrait.get_flattened_data())
portrait.info['transparency']=0
portrait.save(ROOT/'art/firzen/firzen-portrait.png')
portrait.resize((200,200),Image.Resampling.NEAREST).save(ROOT/'art/firzen/portrait/firzen-portrait-4x.png')
sheet=render.read_grh(ROOT/'SYS/FACE.GRH');sheet.putpalette(palette)
preview=Image.new('RGB',(840,240),(235,233,229));draw=ImageDraw.Draw(preview)
for i,(name,img) in enumerate([('Firen',sheet.crop((100,50,150,100))),('Freeze',sheet.crop((200,0,250,50))),('Julian',sheet.crop((250,0,300,50))),('Firzen',portrait)]):
    preview.paste(img.convert('RGB').resize((200,200),Image.Resampling.NEAREST),(10+i*210,10))
    draw.text((10+i*210,216),name,fill=(30,30,30))
preview.save(ROOT/'art/firzen/portrait/firzen-portrait-comparison-4x.png')
used=sorted(set(indices))
assert portrait.size==(50,50) and portrait.getpalette()==palette
assert set(used)<=set(allowed)
report={'dimensions':[50,50],'palette':'original SYS/PAL','indices':used,'hair':[97,98],'source':'builtin imagegen original close-up redraw, facing left','cleanup':'preferred illustration restored; minimal31/34iris planes and cropped-chin contour cleanup; original neck/shading retained','preview_scale':4}
(ROOT/'art/firzen/portrait/portrait-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))

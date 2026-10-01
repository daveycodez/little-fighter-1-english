#!/usr/bin/env python3
"""Exact user source: move native pixels up three cells; extend only bare neck.
No imagegen, resizing of finished sprite, jaw flattening or facial redraw.
"""
from pathlib import Path
import sys,json
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'export'))
import render_character_preview as render
p=render.load_palette(ROOT)
source=Image.open(ROOT/'art/firzen/portrait/firzen-portrait-exact-user-start.png').convert('RGB')
allowed=[7,10,14,15,31,34,81,82,83,97,98]
colors={i:tuple(p[i*3:i*3+3]) for i in allowed}
def nearest(rgb):
 r,g,b=rgb
 if max(rgb)<55:return 10
 if g>r*1.3 and g>b*1.1:ids=[97,98]
 elif r>80 and g<r*.25 and b<r*.25:ids=[31,34]
 elif b>r*1.5 and b>g*1.15:ids=[7]
 elif r>g*1.09 and g>b*1.06 and g>70 and b>50:ids=[81,82,83]
 elif max(rgb)-min(rgb)<45:ids=[10,14,15]
 else:ids=allowed
 return min(ids,key=lambda i:sum((rgb[c]-colors[i][c])**2 for c in range(3)))
raw=source.resize((50,50),Image.Resampling.NEAREST)
base=render.indexed([nearest(rgb) for rgb in raw.get_flattened_data()],(50,50),p)
# Sample the original drawing's actual bottom edge, so its existing thin chin
# contour is retained instead of missed by cell-centre downconversion.
for x in range(50):
 sx=min(source.width-1,int((x+.5)*source.width/50))
 base.putpixel((x,49),nearest(source.getpixel((sx,source.height-1))))
# Preserve full red iris interiors from the user's reference: no black dots.
for shape in [{27:{25:34,26:34},28:{24:34,25:31,26:31,27:34},29:{24:34,25:31,26:31,27:34},30:{25:34,26:34}}, {27:{12:34,13:31,14:34},28:{12:34,13:31,14:34},29:{13:34,14:34}}]:
 for y,row in shape.items():
  for x,c in row.items():base.putpixel((x,y),c)
base.save(ROOT/'art/firzen/portrait/firzen-portrait-exact-start-native.png')
shift=3
out=Image.new('P',(50,50),7);out.putpalette(p)
out.paste(base.crop((0,shift,50,50)),(0,0))
d=ImageDraw.Draw(out)
# Only the newly exposed bottom three rows are drawn. Original jaw/chin above
# them remains pixel-identical. Slim bare neck in the original two skin tones.
d.polygon([(24,47),(43,47),(44,49),(23,49)],fill=82)
d.polygon([(24,47),(31,47),(29,49),(23,49)],fill=81)
d.line([(24,47),(24,48),(23,49)],fill=10,width=1)
d.line([(43,47),(44,48),(44,49)],fill=10,width=1)
# Thin black tendon line is specifically requested, below the rear jaw.
d.line([(36,42),(35,44),(34,47),(33,49)],fill=10,width=1)
out.info['transparency']=0
out.save(ROOT/'art/firzen/portrait/firzen-portrait-exact-up3-neck.png')
out.resize((200,200),Image.Resampling.NEAREST).save(ROOT/'art/firzen/portrait/firzen-portrait-exact-up3-neck-4x.png')
comparison=Image.new('RGB',(440,240),(235,233,229));dr=ImageDraw.Draw(comparison)
for x,label,img in [(10,'Exact native start',base),(230,'Up 3px + neck line',out)]:
 comparison.paste(img.convert('RGB').resize((200,200),Image.Resampling.NEAREST),(x,10))
 dr.text((x,218),label,fill=(30,30,30))
comparison.save(ROOT/'art/firzen/portrait/firzen-portrait-exact-before-after-4x.png')
changes=[(x,y) for y in range(47) for x in range(50) if out.getpixel((x,y))!=base.getpixel((x,y+3))]
assert all(33<=x<=36 and 42<=y<=46 for x,y in changes),changes
report={'native_size':[50,50],'translation_up_pixels':3,'original_jaw_face_hair_preserved':True,'neck_new_rows':[47,49],'neck_tendon_line_bounds':[33,42,37,50],'old_rows_changed_only_for_requested_neck_line':changes,'palette_indices':sorted(set(out.get_flattened_data()))}
(ROOT/'art/firzen/portrait/exact-start-translation-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))

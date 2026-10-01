#!/usr/bin/env python3
"""Build Firzen's additional LF1 assets; original SYS files are read-only inputs."""
from pathlib import Path
import json,re,struct,sys
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'export'))
import render_character_preview as render


def write_grh(path,image):
    header=bytearray(300);struct.pack_into('>HH',header,0,*image.size)
    path.write_bytes(header+image.tobytes())


def build_assets(root=ROOT):
    palette=render.load_palette(root)
    approved=json.loads((root/'art/firzen/firzen-approved.json').read_text())
    head_path=root/approved['assets']['head']
    hair_light,hair_dark=approved['hair_palette_pair']
    head_pixels,_=render.custom_head(head_path,palette)
    head=render.indexed(head_pixels,(17,12),palette)
    atlas=render.read_grh(root/'SYS/HEAD.GRH')
    expanded=Image.new('P',(216,65));expanded.putpalette(palette)
    for row in range(5):
        for column in range(11):
            expanded.paste(atlas.crop((column*18,row*13,column*18+18,row*13+13)),(column*18,row*13))
        expanded.paste(head,(11*18+1,row*13+1))
    write_grh(root/'SYS/FZHEAD.GRH',expanded)
    menu=render.read_grh(root/'SYS/HEAD2.GRH');extra=Image.new('P',(216,16));extra.putpalette(palette);extra.paste(menu,(0,0))
    # The menu includes a jaw; retain Davis's three native jaw rows, same skin.
    menu_face=menu.crop((1,1,18,16));menu_face.putpalette(palette);menu_face.paste(head,(0,0));extra.paste(menu_face,(199,1))
    write_grh(root/'SYS/FZHEAD2.GRH',extra)
    face=render.read_grh(root/'SYS/FACE.GRH');face.putpalette(palette)
    portrait_path=root/'art/firzen/firzen-portrait.png'
    if portrait_path.exists():
        portrait=Image.open(portrait_path).convert('RGBA')
        if portrait.size!=(50,50):raise ValueError('Firzen portrait must be native50x50')
        pixels=[0 if a<128 else render.nearest_color((r,g,b),palette) for r,g,b,a in portrait.get_flattened_data()]
        portrait=render.indexed(pixels,(50,50),palette)
    else:
        # A complete native game sprite is the functional menu portrait until
        # a dedicated portrait is supplied. No resizing of its pixels.
        portrait=Image.new('P',(50,50));portrait.putpalette(palette)
        record={'name':'Firzen','skin':[83,81],'shirt':[66,77],'trousers':[11,10],'hair':hair_light}
        body,_,_=render.render_character(root,palette,record,2,head_path)
        portrait.paste(body,(13,18))
    face.paste(portrait,(250,50));write_grh(root/'SYS/FZFACE.GRH',face)
    original_act=render.read_grh(root/'SYS/ACT2.GRH');act=Image.new('P',(312,156));act.putpalette(palette);act.paste(original_act,(0,0))
    for column,n in enumerate([111,112,113,114,93]):
        j=n-61;x=j%12*26+1;y=j//12*26+1
        source=render.crop_pixels(original_act,(x,y,x+25,y+25))
        mapping=({84:83,82:81,7:66,6:77,109:11,110:10,132:hair_light,134:hair_dark,121:31} if n!=93 else {82:83,145:66,146:77,67:11,68:10,77:hair_light,78:hair_dark,117:31})
        sprite=render.indexed([mapping.get(v,v) for v in source],(25,25),palette)
        act.paste(sprite,(column*26+1,131))
    write_grh(root/'SYS/FZACT2.GRH',act)
    cannon=Image.new('P',(29,31));cannon.putpalette(palette)
    for name,y in [('firzen-ball-v2.png',0),('firzen-cannon-segment-v4.png',16)]:
        image=Image.open(root/'art/firzen'/name)
        if image.mode!='P' or image.getpalette()!=palette:raise ValueError('Cannon needs native LF1 indices')
        cannon.paste(image,(0,y))
    write_grh(root/'SYS/FZCANNON.GRH',cannon)
    original=(root/'SYS/DATA.DAT').read_text()
    blocks=list(re.finditer(r'^\d+\.\s*([^\r\n]+)',original,re.M));last=blocks[10];end=original.index('\nE',last.end())
    character='\n12. Firzen\n\n    Head: 12\n    Face: 6 2\n     Skn: 83 81\n     Sht: 66 77\n     Trs: 11 10\n      Sp: A  35  43  27   0   1   50\n          B  35  43  29   0   1  100\n          E 121 122 123 124  18  125\n'
    data=original[:end]+character+original[end:]
    color_start=data.index('\nE',end)+3;color_end=data.index('Background:',color_start)
    rows=[line.strip() for line in data[color_start:color_end].splitlines() if line.strip()]
    additions=[hair_light,0,0,0,0]
    if len(rows)!=5:raise ValueError('Expected five head-color rows')
    expanded_colors='\n'+''.join(' '+row+' '+str(extra)+'\n' for row,extra in zip(rows,additions))+'\n'
    data=data[:color_start]+expanded_colors+data[color_end:]
    marker=data.index('\nE',data.index(' Fire_Bird') if ' Fire_Bird' in data else data.index('Fire_Bird'))
    new_weapons='\n FirzenLead   27     1  2  2  20  1        33  34  22        4\n FirzenTrail  28     1  2  2  12  1        33  34  22        4\n FirzenFire   29     1  2  2  20  1        41  42  22        4\n FirzenIce    30     1  2  6  12  1        49  50  23        4\n'
    data=data[:marker]+new_weapons+data[marker:]
    (root/'SYS/FZDATA.DAT').write_text(data)
    # Selection loads SUPERL for character12. Supply a full native move panel
    # rather than allowing the game's fatal missing-file path to run.
    panel=render.read_grh(root/'SYS/SUPERI.GRH');panel.putpalette(palette)
    native_border=panel.copy()
    # Use the exact 8x9 letter pixels baked into the existing English panels.
    # Runtime NEWFONTS is a different, narrow font and must not be used here.
    glyphs={}
    sources=[('A','Davis',44),('B','Woody',44),('C','Louis',44),('D','Henry',44),
             ('E','Deep',44),('F','Firen',44),('G','Dennis',44),('H','John',44),
             ('I','Freeze',44),('J','Rudolf',44),('K','Julian',44),
             ('I','Ice Blast',60),('I','Ice Sword',92),('I','Whirlwind',124),
             ('D','Arrow',60),('A','Dragon Punch',124),('C','Phoenix Palm',124)]
    for suffix,text,y in sources:
        source=render.read_grh(root/f'SYS/SUPER{suffix}.GRH')
        for i,ch in enumerate(text):
            mask=Image.new('1',(7,9));mask.putdata([source.getpixel((2+i*8+x,y+py))==15 if 2+i*8+x<source.width else False for py in range(9) for x in range(7)])
            glyphs.setdefault(ch,mask)
    # Move titles can have different kerning from the character names.
    # Ice Blast's narrow initial I puts c at x=8, not the guessed x=10.
    for ch,suffix,x,y in [('c','I',8,60),('a','A',10,44)]:
        source=render.read_grh(root/f'SYS/SUPER{suffix}.GRH')
        mask=Image.new('1',(7,9))
        mask.putdata([source.getpixel((x+px,y+py))==15 for py in range(9) for px in range(7)])
        glyphs[ch]=mask
    # New capital letters use the identical DOS serif bitmap family.
    for ch,rows in {'C':['.#####.','##...##','##.....','##.....','##.....','##.....','##.....','##...##','.#####.'],
                    'V':['##...##','##...##','##...##','##...##','##...##','.##.##.','.##.##.','..###..','...#...']}.items():
        glyphs[ch]=Image.new('1',(7,9));glyphs[ch].putdata([v=='#' for row in rows for v in row])
    # A space is empty; cropped labels can place neighboring ink in its cell.
    glyphs[' ']=Image.new('1',(7,9))
    draw=ImageDraw.Draw(panel)
    def text_at(x,y,text,target=None):
        target=panel if target is None else target
        for ch in text:
            target.paste(15,(x+2,y,x+9,y+9),glyphs[ch]);x+=8
    draw.rectangle((1,43,51,53),fill=108);text_at(0,44,'Firzen')
    # DATA costs are in internal 2.5-unit points, like every stock character.
    for row,name in enumerate(['Cannon','Disaster','Polar Volcano']):
        y=60+32*row
        # Replace the entire title band with a freshly drawn opaque image.
        # No pixels from the previous move label can remain underneath.
        title=Image.new('P',(104,16),108);title.putpalette(palette)
        text_at(-1,3,name,target=title)
        panel.paste(title,(1,y-3))
        draw.rectangle((77,y+14,104,y+25),fill=108)
        cost_source=render.read_grh(root/('SYS/SUPERI.GRH' if row<2 else 'SYS/SUPERD.GRH'))
        source_y=75 if row==0 else 107
        panel.paste(cost_source.crop((78,source_y,106,source_y+10)),(78,y+15))
    # Restore both outermost columns after all text/cost overlays.
    panel.paste(native_border.crop((0,0,1,panel.height)),(0,0))
    panel.paste(native_border.crop((panel.width-1,0,panel.width,panel.height)),(panel.width-1,0))
    write_grh(root/'SYS/FZSUPER.GRH',panel)
    return ['FZHEAD.GRH','FZHEAD2.GRH','FZFACE.GRH','FZACT2.GRH','FZCANNON.GRH','FZDATA.DAT','FZSUPER.GRH']


if __name__=='__main__':
    for name in build_assets():print(name)

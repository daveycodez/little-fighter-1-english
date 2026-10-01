#!/usr/bin/env python3
"""Choreographed LF1 sprite fight with dialogue: Firzen vs Julian.

Research/mockup only. No game executable, data, palette, or GRH is changed.
Native 320x180, fixed18.2Hz sampling, exactly4x nearest-neighbor output.
The story is scripted; motion, damage and timing are illustrative.
"""
from pathlib import Path
import argparse,json,math,textwrap,hashlib
from PIL import Image,ImageDraw,ImageFont
import render_character_preview as m
from render_blast_preview import frame_samples
from render_combat_preview import road_background


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('art/previews/firzen-vs-julian-dialogue-fight-16x9-4x.gif'))
    args=parser.parse_args();root=Path(__file__).resolve().parent.parent;pal=m.load_palette(root);fps=18.2
    protected=[root/'SYS'/name for name in ['FIGHT.EXE','START.EXE','DATA.DAT','PAL','ACT1.GRH','ACT2.GRH','HEAD.GRH','WEAPON.GRH']]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    a1=m.read_grh(root/'SYS/ACT1.GRH');a2=m.read_grh(root/'SYS/ACT2.GRH');head_atlas=m.read_grh(root/'SYS/HEAD.GRH');weapons=m.read_grh(root/'SYS/WEAPON.GRH')
    records={'firzen':{'name':'Firzen','skin':[83,81],'shirt':[66,77],'trousers':[11,10],'hair':97},'julian':m.original_characters(root)['julian']}
    firzen_head=m.custom_head(root/'art/firzen/firzen-head-gameplay-v51.png',pal)[0]
    heads={'firzen':firzen_head};hid=records['julian']['head_id'];hx=(hid-1)%11*18+1;hy=(hid-1)//11*13+1
    heads['julian']=m.crop_pixels(head_atlas,(hx,hy,hx+17,hy+12))
    actors={'firzen':{'x':72.,'y':138.,'z':0.,'pose':2,'hp':100.,'left':False},'julian':{'x':246.,'y':138.,'z':0.,'pose':2,'hp':100.,'left':True}}
    cache={};font=ImageFont.load_default(size=9);small=ImageFont.load_default(size=8)
    background=road_background(root,pal).convert('RGBA');frames=[];delays=[];scenes=[];dialogue_log=[];events=[];time_ms=0
    rgb_index={tuple(pal[i*3:i*3+3]):i for i in reversed(range(151))}
    used_poses={'firzen':set(),'julian':set()};max_jump={'firzen':0.,'julian':0.};walk_counts={'firzen':0,'julian':0};specials={'firzen':set(),'julian':set()}

    def tile(n):
        atlas=a1 if n<=60 else a2;j=(n-1)%60;x=j%12*26+1;y=j//12*26+1
        return m.crop_pixels(atlas,(x,y,x+25,y+25))

    def sprite(who,n,left=False):
        key=(who,n,left)
        if key in cache:return cache[key]
        r=records[who];remap=dict(zip(range(151,161),r['skin']+r['shirt']+r['trousers']+[15,31,10,r['hair']]))
        pixels=[remap.get(v,v) for v in tile(n)]
        if n<=60:
            # Exact head gates/offsets initialized by LF1. Special Julian poses
            # and airborne/hurt poses contain their own face and hair.
            baked=(12<=n<=20 or n in [22,23,26,27,28,29,30,31,37,38,39,47,48,50,51] or 33<=n<=43 or 52<=n<=56 or n>=61)
            if not baked:
                ox=5 if n==25 else 4 if n in [7,11,24] else 3 if n in [44,45,46] else 0
                oy=3 if n==21 else 0
                for yy in range(12):
                    for xx in range(17):
                        v=heads[who][yy*17+xx]
                        if v:pixels[(yy+oy)*25+xx+ox]=v
        elif who=='firzen':
            if 111<=n<=114:fixed={84:83,82:81,7:66,6:77,109:11,110:10,132:97,134:98,121:31}
            elif n==93:fixed={82:83,145:66,146:77,67:11,68:10,77:97,78:98,117:31}
            else:fixed={}
            pixels=[fixed.get(v,v) for v in pixels]
        image=m.indexed(pixels,(25,25),pal).convert('RGBA')
        if left:image=image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        cache[key]=image;return image

    def weapon(n,left=False):
        key=('weapon',n,left)
        if key not in cache:
            x=(n-1)%15*18+1;y=(n-1)//15*14+1
            image=m.indexed(m.crop_pixels(weapons,(x,y,x+17,y+13)),(17,13),pal).convert('RGBA')
            cache[key]=image.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if left else image
        return cache[key]

    def explosion(fire,phase):
        x=([163,199,235] if fire else [55,91,127])[phase]
        return m.indexed(m.crop_pixels(weapons,(x,81,x+35,110)),(35,29),pal).convert('RGBA')

    shadow_pixels=tile(49);shadow=m.indexed([10 if v else 0 for v in shadow_pixels],(25,25),pal).convert('RGBA')
    shadow=shadow.crop(shadow.getchannel('A').getbbox())
    assert shadow.size==(9,1)
    lead=Image.open(root/'art/firzen/firzen-ball-v2.png').convert('RGBA');segment=Image.open(root/'art/firzen/firzen-cannon-segment-v4.png').convert('RGBA')

    def bubble(stage,who,text):
        a=actors[who];draw=ImageDraw.Draw(stage);draw.fontmode='1'
        lines='\n'.join(line for paragraph in text.split('\n') for line in textwrap.wrap(paragraph,20))
        box=draw.multiline_textbbox((0,0),lines,font=font,spacing=1)
        w=box[2]-box[0]+10;h=box[3]-box[1]+10
        x=max(3,min(317-w,round(a['x']-w/2)));y=max(31,round(a['y']-a['z']-30-h-7))
        draw.rounded_rectangle((x+1,y+1,x+w+1,y+h+1),radius=3,fill=(48,48,48,255))
        draw.rounded_rectangle((x,y,x+w,y+h),radius=3,fill=(252,252,252,255),outline=(0,0,0,255),width=1)
        tail=max(x+5,min(x+w-5,round(a['x'])));draw.polygon([(tail-3,y+h),(tail+3,y+h),(tail,y+h+6)],fill=(252,252,252,255),outline=(0,0,0,255))
        draw.line((tail-2,y+h,tail+2,y+h),fill=(252,252,252,255))
        draw.multiline_text((x+5,y+4-box[1]),lines,font=font,spacing=1,fill=(0,0,0,255))
        assert 0<=x<x+w<320 and y>=31 and y+h+6<180

    def draw_frame(extra,bubbles,delay):
        stage=background.copy()
        for who,a in actors.items():
            stage.alpha_composite(shadow,(round(a['x'])-4,round(a['y'])+1))
        for who in sorted(actors,key=lambda w:actors[w]['y']):
            a=actors[who];image=sprite(who,a['pose'],a['left']);used_poses[who].add(a['pose']);max_jump[who]=max(max_jump[who],a['z'])
            if a['pose'] in [1,2,3,24,25]:walk_counts[who]+=1
            stage.alpha_composite(image,(round(a['x'])-12,round(a['y']-a['z'])-24))
        for image,x,y in extra:stage.alpha_composite(image,(round(x),round(y)))
        hud=ImageDraw.Draw(stage);hud.fontmode='1';hud.rectangle((0,0,319,26),fill=(48,48,48,255))
        for who,x,color in [('firzen',8,66),('julian',202,48)]:
            hud.text((x,1),records[who]['name'].upper(),font=small,fill=(252,252,252,255))
            hud.rectangle((x,12,x+108,21),fill=(0,0,0,255));hud.rectangle((x+1,13,x+107,20),fill=(96,96,96,255))
            hp=max(0,min(100,actors[who]['hp']));length=round(106*hp/100)
            if length:hud.rectangle((x+1,13,x+length,20),fill=tuple(pal[color*3:color*3+3])+(255,))
            if hp==0:hud.text((x+80,1),'KO',font=small,fill=(252,252,252,255))
        for who,line in bubbles:bubble(stage,who,line)
        rgb=stage.convert('RGB');native=Image.new('P',(320,180));native.putpalette(pal);native.putdata([rgb_index[v] for v in rgb.get_flattened_data()])
        assert native.convert('RGB').tobytes()==rgb.tobytes()
        frames.append(native);delays.append(delay)

    def play(name,duration,callback,lines=[]):
        nonlocal time_ms
        start=time_ms
        for who,begin,end,text in lines:dialogue_log.append({'scene':name,'speaker':who,'start_ms':start+begin,'end_ms':start+end,'text':text})
        for elapsed,delay in frame_samples(duration,fps):
            extra=callback(elapsed/1000) or []
            active=[(who,text) for who,begin,end,text in lines if begin<=elapsed<end]
            draw_frame(extra,active,delay)
        scenes.append({'name':name,'start_ms':start,'duration_ms':duration});time_ms+=duration

    def idle(t):
        for a in actors.values():a['pose']=2;a['z']=0
        return []

    def walk(who,start,end,t,duration,fast=False):
        a=actors[who];u=min(1,t/duration);a['x']=start+(end-start)*u;a['z']=0;a['pose']=(24+int(t*9)%2) if fast else (1+int(t*7)%3)

    def jump(who,start,end,t,duration,height=29):
        a=actors[who];u=max(0,min(1,t/duration));a['x']=start+(end-start)*u;a['z']=4*height*u*(1-u)
        a['pose']=15 if u<.22 else 19 if u<.52 else 20 if u<.82 else 21

    def knock(who,start,t,side=1):
        age=max(0,t);a=actors[who];u=min(1,age/.38);a['x']=start+side*18*u;a['z']=9*math.sin(math.pi*u)
        a['pose']=16 if age<.12 else 17 if age<.32 else 18

    def rise(who,t):
        a=actors[who];a['z']=0;a['pose']=18 if t<.55 else 21 if t<.85 else 15 if t<1.03 else 2

    # Intro and a moving close-range exchange.
    play('opening',2600,idle,[('julian',0,2450,'Two elements.\nStill one loser.')])
    play('answer',2100,idle,[('firzen',0,2000,'Then lose\nto both.')])
    def approach(t):walk('firzen',72,133,t,1.5);walk('julian',246,177,t,1.5)
    play('walk into range',1500,approach);actors['firzen']['x']=133;actors['julian']['x']=177
    def melee(t):
        f,j=actors['firzen'],actors['julian'];f['x']=133+8*min(t/.4,1);j['x']=177-10*min(t/.4,1)
        f['pose']=[6,7,8,9,10,11][int(t*8)%6] if t<1.35 else 2;j['pose']=[6,7,8][int(t*8)%3] if t<.8 else 14 if t<1.1 else 15 if t<1.35 else 2
        if t>.5:j['hp']=95
        if t>1.0:f['hp']=90
        return [(weapon(12+int(t*12)%2),151,116)] if .4<t<1.25 else []
    play('melee exchange',1800,melee)
    def retreat(t):walk('firzen',141,91,t,1.2);jump('julian',167,234,t,1.2,24)
    play('separate',1200,retreat);actors['firzen']['x']=91;actors['julian']['x']=234
    play('skull threat',1800,idle,[('julian',0,1750,'Meet the family.')])

    # Julian's Skulls: Firzen jumps over a homing stream.
    specials['julian'].add('skulls');events.append({'special':'julian_skulls','time_ms':time_ms})
    skull_particles=[];skull_impact_times=[]
    def skulls(t):
        j=actors['julian'];j['pose']=54 if t<1.5 else 43 if t<2 else 2
        if .45<t<1.45:jump('firzen',91,119,t-.45,1,31)
        elif 1.7<t<2.7:jump('firzen',119,94,t-1.7,1,28)
        else:actors['firzen']['pose']=2;actors['firzen']['z']=0
        extra=[]
        for k in range(7):
            born=.35+k*.17
            if t>=born and not any(p['index']==k for p in skull_particles):
                skull_particles.append({'index':k,'x':220.,'y':138.+(k%3-1)*3,
                                        'vx':-8.,'vy':0.,'hit':False})
        f=actors['firzen']
        for particle in skull_particles:
            if particle['hit']:continue
            particle['vx']=max(-17.,min(17.,particle['vx']+(2. if f['x']>=particle['x'] else -2.)))
            particle['vy']=max(-3.,min(3.,particle['vy']+(1. if f['y']>=particle['y'] else -1.)))
            particle['x']+=particle['vx']*.5;particle['y']+=particle['vy']*.5
            if abs(particle['x']-f['x'])<11 and abs(particle['y']-f['y'])<7 and f['z']<7:
                particle['hit']=True;skull_impact_times.append(t)
                f['hp']=max(80,f['hp']-3)
            else:
                extra.append((weapon(91+int(t*fps/2)%2,particle['vx']<0),particle['x']-8,particle['y']-18))
        for impact_t in skull_impact_times:
            if 0<=t-impact_t<.16:extra.append((weapon(12),f['x']-8,f['y']-20))
        return extra
    play('skulls and jumps',3300,skulls,[('firzen',1650,3150,'All skull.\nNo brains.')]);actors['firzen']['x']=94;actors['firzen']['z']=0

    # Firzen Cannon, with a two-second hold and full projectile exit.
    specials['firzen'].add('cannon');events.append({'special':'firzen_cannon','time_ms':time_ms})
    cannon_hits=[]
    def cannon(t):
        f,j=actors['firzen'],actors['julian'];f['pose']=35 if t<.3 else 43 if t<2.3 else 2
        f['z']=0;extra=[]
        for tick in range(0,37,3):
            born=.3+tick/fps
            if t<born:continue
            image=lead if tick==0 else segment;x=107+100*(t-born)
            if tick<9 and x+image.width>=j['x']-7:
                if tick not in cannon_hits:cannon_hits.append(tick)
                continue
            if x<320:extra.append((image,x,125-image.height//2))
        if t>.95:
            if t<1.48:j['pose']=14 if int(t*fps)%3<2 else 15;j['x']=234+3*min(len(cannon_hits),3)
            else:knock('julian',243,t-1.48,1)
            j['hp']=70
            if t<1.62:extra.append((weapon([46,47,48][int(t*fps)%3]),j['x']-12,117))
        return extra
    play('cannon counter',4900,cannon,[('firzen',500,2450,'Smile for\nthe flash.')]);actors['julian']['x']=261
    play('julian gets up',1900,lambda t:rise('julian',t),[('julian',950,1800,'Cheap tricks.')])

    # Julian's charged energy shot knocks Firzen down.
    specials['julian'].add('charge');events.append({'special':'julian_charge','time_ms':time_ms})
    def charge(t):
        j=actors['julian'];j['pose']=52 if t<.65 else 53 if t<1.0 else 2
        extra=[]
        if .65<=t<1.85:extra.append((explosion(False,1),j['x']-30-126*(t-.65),108))
        if t>=1.8:knock('firzen',94,t-1.8,-1);actors['firzen']['hp']=58
        return extra
    play('charged blast',3000,charge,[('julian',150,2000,'THIS is power.')]);actors['firzen']['x']=76
    def recover_jump(t):
        if t<1.0:rise('firzen',t)
        else:jump('firzen',76,102,t-1.0,1.1,27)
    play('jump back in',2200,recover_jump,[('firzen',400,2100,'Could use\na cool-down.')]);actors['firzen']['x']=102;actors['firzen']['z']=0

    # Disaster: upper fire, lower ice, upper fire, lower ice, one emission each.
    specials['firzen'].add('overwhelming_disaster');events.append({'special':'firzen_disaster','time_ms':time_ms})
    balls=[];damage_flags=set()
    def disaster(t):
        f,j=actors['firzen'],actors['julian'];tick=round(t*fps);extra=[]
        f['pose']=35 if tick<6 else (43 if (tick-6)%6<3 else 35) if tick<=26 else 2
        for i,born_tick in enumerate([6,12,18,24]):
            if tick>=born_tick and not any(b['i']==i for b in balls):
                balls.append({'i':i,'kind':'fire' if i%2==0 else 'ice','x':116.,'y':132. if i%2==0 else 144.,'vx':8.,'vy':-3. if i%2==0 else 3.,'hit':False})
        for b in balls:
            if b['hit']:continue
            b['vx']=max(-17,min(17,b['vx']+(2 if j['x']>=b['x'] else -2)))
            b['vy']=max(-3,min(3,b['vy']+(1 if 138>=b['y'] else -1)))
            b['x']+=b['vx']*.5;b['y']+=b['vy']*.5
            if abs(b['x']-j['x'])<15 and abs(b['y']-138)<10:
                b['hit']=True;b['hit_t']=t;damage_flags.add(b['i']);j['hp']=max(38,70-len(damage_flags)*8)
                events.append({'event':'elemental_hit','kind':b['kind'],'time_ms':time_ms+round(t*1000)})
            else:extra.append((weapon((41 if b['kind']=='fire' else 49)+int(t*9)%2,b['vx']<0),b['x']-8,b['y']-18))
        hits=[b for b in balls if b['hit']]
        if hits:
            latest=max(hits,key=lambda b:b['hit_t']);age=t-latest['hit_t']
            duration=.7 if latest['kind']=='fire' else .95
            if age<duration:j['pose']=36 if latest['kind']=='fire' else 42;j['z']=0
            else:knock('julian',261,age-duration,1)
        return extra
    play('elemental chase',4500,disaster,[('firzen',150,1850,'Hot. Cold.\nTake your pick.')]);actors['julian']['x']=279;actors['julian']['hp']=38
    assert len(balls)==4 and all(b['hit'] for b in balls)
    def jul_recover(t):rise('julian',t)
    play('julian rises again',1700,jul_recover,[('julian',950,1680,'Enough!')])

    # Big Bang: Julian closes in and lands his strongest blast.
    specials['julian'].add('big_bang');events.append({'special':'julian_big_bang','time_ms':time_ms})
    def big_bang(t):
        f,j=actors['firzen'],actors['julian'];extra=[]
        if t<1:
            walk('julian',279,153,t,1,True);walk('firzen',102,129,t,1)
        elif t<1.7:j['x']=153;j['pose']=55;f['x']=129;f['pose']=35
        else:
            j['pose']=56 if t<2.05 else 2;age=t-1.7
            knock('firzen',129,age,-1);f['hp']=22
            if age<.34:extra.append((explosion(False,min(2,int(age*fps)//2)),136,111))
        return extra
    play('big bang',4000,big_bang,[('julian',1050,2350,'KNEEL!'),('firzen',2750,3970,'Okay. That\none hurt.')]);actors['firzen']['x']=111;actors['julian']['x']=153
    def clutch(t):
        if t<1.1:rise('firzen',t)
        else:walk('firzen',111,124,t-1.1,.9)
        walk('julian',153,168,t,2)
    play('last stand',2000,clutch);actors['firzen']['x']=124;actors['julian']['x']=168
    play('last threat',1800,idle,[('julian',0,1730,'Stay down!')])
    play('final answer',1600,idle,[('firzen',0,1530,'First, chill.')])

    # Arctic Volcano freezes Julian in place and immediately ignites/blasts him.
    specials['firzen'].add('arctic_volcano');events.append({'special':'firzen_arctic_volcano','time_ms':time_ms})
    def volcano(t):
        f,j=actors['firzen'],actors['julian'];extra=[]
        if t<.3:walk('firzen',124,146,t,.3);j['pose']=2
        elif t<1.6:
            f['x']=146;f['pose']=111+int((t-.3)*fps/2)%4;j['pose']=42;j['x']=168;j['z']=0
        else:
            age=t-1.6;f['pose']=93 if age<.34 else 2;j['hp']=0
            j['x']=168+min(1,age/.4)*23;j['z']=9*math.sin(math.pi*min(1,age/.4))
            j['pose']=36 if age<.36 else 18
            if age<.34:extra.append((explosion(True,min(2,int(age*fps)//2)),129,111))
        return extra
    play('arctic volcano finish',4000,volcano,[('julian',600,1250,'W-wait...'),('firzen',1300,2350,'Now thaw.')])
    actors['firzen']['x']=146;actors['firzen']['pose']=2;actors['julian']['x']=191;actors['julian']['pose']=18;actors['julian']['z']=0
    def victory(t):actors['firzen']['pose']=2;actors['julian']['pose']=18;actors['julian']['z']=0
    play('firzen wins',2700,victory,[('firzen',0,2600,'Two elements.\nOne winner.')])
    assert actors['firzen']['hp']>0 and actors['julian']['hp']==0
    assert specials['firzen']=={'cannon','overwhelming_disaster','arctic_volcano'}
    assert specials['julian']=={'skulls','charge','big_bang'}
    assert max_jump['firzen']>=25 and len(used_poses['firzen'])>=15
    assert max_jump['julian']>=20 and len(used_poses['julian'])>=15
    args.output.parent.mkdir(parents=True,exist_ok=True)
    native_path=args.output.with_name(args.output.stem+'-native.gif')
    frames[0].save(native_path,save_all=True,append_images=frames[1:],duration=delays,loop=0,optimize=False,disposal=1)
    scaled=[f.resize((1280,720),Image.Resampling.NEAREST) for f in frames]
    scaled[0].save(args.output,save_all=True,append_images=scaled[1:],duration=delays,loop=0,optimize=False,disposal=1)
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    meta={'scope':'scripted research mockup; no game executable or data modified','native_canvas':[320,180],'preview_canvas':[1280,720],'fps':fps,'scale':4,'hair':[97,98],'shirt':[66,77],'pants':[11,10],'winner':'Firzen','finisher':'Arctic Volcano','duration_ms':sum(delays),'scenes':scenes,'dialogue':dialogue_log,'events':events,'specials':{w:sorted(v) for w,v in specials.items()},'used_poses':{w:sorted(v) for w,v in used_poses.items()},'max_jump_height':max_jump,'shadow_source':'ACT1.GRH frame49, original9x1 mask','protected_hashes':hashes}
    args.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    with Image.open(args.output) as gif:
        total=0
        for i in range(gif.n_frames):gif.seek(i);total+=gif.info['duration']
        assert total==sum(delays) and gif.size==(1280,720)
        print(f'Saved {args.output}: {gif.n_frames} frames, {total/1000:.1f}s, all six specials, dialogue, shadows, Firzen wins.')


if __name__=='__main__':main()

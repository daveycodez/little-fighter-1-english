#!/usr/bin/env python3
"""Render all three Firzen specials as an LF1-asset research mockup.

No executable or game DATA is changed. Native 320x180 canvas, 4x output.
Cannon uses the approved 100px/sec, 3-tick, 2-second settings. Disaster emits
exactly fire/ice/fire/ice in top/bottom/top/bottom lanes, one per emission.
The original sprites chase enemies using skull-style steering.
Arctic Volcano reuses Freeze's spin poses followed immediately by Firen's
explosion: contact freezes targets in place, then fire knocks them away.
Dedicated elemental collision/status timing remains illustrative.
"""
from pathlib import Path
import argparse,json,math,random,subprocess,sys,tempfile,hashlib
from PIL import Image,ImageDraw,ImageFont
import render_character_preview as m
from render_blast_preview import frame_samples
from render_combat_preview import road_background


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hair-highlight',type=int,choices=range(1,151),default=97)
    parser.add_argument('--hair-shadow',type=int,choices=range(1,151),default=98)
    parser.add_argument('--output',type=Path,default=Path('art/previews/firzen-all-three-specials-jade-97-98-v5-16x9-4x.gif'))
    args=parser.parse_args();root=Path(__file__).resolve().parent.parent;pal=m.load_palette(root);fps=18.2
    game_paths=[root/'SYS/FIGHT.EXE',root/'SYS/START.EXE',root/'SYS/DATA.DAT',root/'SYS/PAL']
    original_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in game_paths}
    raw1=m.read_grh(root/'SYS/ACT1.GRH');raw2=m.read_grh(root/'SYS/ACT2.GRH');weapons=m.read_grh(root/'SYS/WEAPON.GRH')
    original=m.original_characters(root);hair=[args.hair_highlight,args.hair_shadow]
    firzen={'name':'Firzen','skin':[83,81],'shirt':[66,77],'trousers':[11,10],'hair':hair[0]}
    bg=road_background(root,pal).convert('RGBA');frames=[];durations=[];events=[];section_stats={}
    font=ImageFont.load_default(size=10)
    rgb_indices={tuple(pal[i*3:i*3+3]):i for i in reversed(range(151))}

    def emit(stage,delay,title):
        rgb=stage.convert('RGB');draw=ImageDraw.Draw(rgb);draw.fontmode='1'
        draw.rectangle((0,0,319,16),fill=(48,48,48));draw.text((8,2),title,font=font,fill=(252,252,252))
        native=Image.new('P',(320,180));native.putpalette(pal);native.putdata([rgb_indices[v] for v in rgb.get_flattened_data()])
        assert native.convert('RGB').tobytes()==rgb.tobytes()
        frames.append(native.resize((1280,720),Image.Resampling.NEAREST));durations.append(delay)

    with tempfile.TemporaryDirectory(prefix='firzen-three-moves-') as temp:
        head_path=Path(temp)/'head.png';head=m.custom_head(root/'art/firzen/firzen-head-gameplay-v50.png',pal)[0]
        head=[hair[0] if v==98 else hair[1] if v==99 else v for v in head]
        m.indexed(head,(17,12),pal).save(head_path,transparency=0)
        cache={}
        def actor(record,frame=2,left=False):
            key=(record['name'],frame,left)
            if key in cache:return cache[key]
            custom=head_path if record['name']=='Firzen' else None
            if frame in m.SUPPORTED_FRAMES:
                image=m.render_character(root,pal,record,frame,custom)[0].convert('RGBA')
            else:
                # Original burning and frozen poses from the native atlas.
                if frame not in [36,42]:
                    raise ValueError(f'Unsupported reaction pose: {frame}')
                x=(frame-1)%12*26+1;y=(frame-1)//12*26+1
                remap=dict(zip(range(151,161),record['skin']+record['shirt']+record['trousers']+[15,31,10,record['hair']]))
                pixels=[remap.get(v,v) for v in m.crop_pixels(raw1,(x,y,x+25,y+25))]
                image=m.indexed(pixels,(25,25),pal).convert('RGBA')
            if left:image=image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            cache[key]=image;return image

        def effect(n):
            x=(n-1)%15*18+1;y=(n-1)//15*14+1
            return m.indexed(m.crop_pixels(weapons,(x,y,x+17,y+13)),(17,13),pal).convert('RGBA')

        # Cannon: reuse the verified combat renderer with the chosen palette pair.
        cannon=Path(temp)/'cannon.gif'
        subprocess.run([sys.executable,'-B',str(root/'export/render_combat_preview.py'),'--speed','100','--shot-ticks','3','--hold-seconds','2','--post-release-ms','2300','--fps',str(fps),'--shirt','66,77','--trousers','11,10','--head',str(head_path),'--hair',str(hair[0]),'--output',str(cannon)],check=True,capture_output=True)
        cannon_meta=json.loads(cannon.with_suffix('.json').read_text())
        assert cannon_meta['timeline'][-1]['visible_projectiles']==0
        with Image.open(cannon) as animation:
            for i in range(animation.n_frames):
                animation.seek(i);display=animation.convert('RGB');native=display.resize((320,180),Image.Resampling.NEAREST)
                assert native.resize(display.size,Image.Resampling.NEAREST).tobytes()==display.tobytes()
                emit(native,animation.info['duration'],'FIRZEN CANNON')
        section_stats['cannon']={'speed_px_sec':100,'shot_interval_ticks':3,'hold_ms':2000,'post_release_ms':2300,'extra_travel_ms':500,'final_projectiles_offscreen':True,'duration_ms':sum(durations)}

        # Disaster: four elemental balls choose enemy targets and turn gradually.
        before=len(frames);rng=random.Random(4)
        targets=[{'name':'davis','x':201.,'y':115.,'base_x':201.,'base_y':115.,'status':None,'status_tick':-999,'hits':0},
                 {'name':'woody','x':224.,'y':155.,'base_x':224.,'base_y':155.,'status':None,'status_tick':-999,'hits':0}]
        projectiles=[];impacts=[];disaster_hits=[];reaction_log=[];spawn_ticks=[6,12,18,24];order=['fire','ice','fire','ice'];launch_lanes=['top','bottom','top','bottom']
        for t,delay in frame_samples(6500,fps):
            tick=round(t*fps/1000);stage=bg.copy()
            for j,target in enumerate(targets):
                if target['status'] is None:
                    target['x']=target['base_x']+10*math.sin(tick*.10+j)
                    target['y']=target['base_y']+4*math.sin(tick*.07+j)
            if tick in spawn_ticks:
                i=spawn_ticks.index(tick);target_index=rng.randrange(len(targets))
                lane=launch_lanes[i]
                launch_y=132. if lane=='top' else 144.
                projectiles.append({'kind':order[i],'lane':lane,'target':target_index,'x':95.,'y':launch_y,'vx':8.,'vy':-3. if lane=='top' else 3.,'hit':False,'spawn':tick})
                events.append({'move':'disaster','event':'spawn','tick':tick,'kind':order[i],'lane':lane,'origin_y':launch_y,'target':targets[target_index]['name']})
            for shot in projectiles:
                if shot['hit']:continue
                target=targets[shot['target']]
                shot['vx']=max(-17.,min(17.,shot['vx']+(2. if target['x']>=shot['x'] else -2.)))
                shot['vy']=max(-3.,min(3.,shot['vy']+(1. if target['y']>=shot['y'] else -1.)))
                shot['x']+=shot['vx']*.5;shot['y']+=shot['vy']*.5
                if abs(shot['x']-target['x'])<13 and abs(shot['y']-target['y'])<9:
                    shot['hit']=True;target['status']='burn' if shot['kind']=='fire' else 'freeze';target['status_tick']=tick;target['fall_tick']=None;target['hits']+=1
                    impacts.append({'tick':tick,'x':round(target['x'])-8,'y':round(target['y'])-19,'kind':shot['kind']})
                    disaster_hits.append(shot['kind']);events.append({'move':'disaster','event':'hit','tick':tick,'kind':shot['kind'],'target':target['name']})
            casting=35 if tick<6 else (43 if (tick-6)%6<3 else 35) if tick<=26 else 2
            stage.alpha_composite(actor(firzen,casting),(70,114))
            for target in targets:
                age=tick-target['status_tick']
                status=target['status']
                if status in ['burn','freeze'] and age >= (22 if status=='burn' else 38):
                    target['status']='fall'
                    target['fall_tick']=tick
                    target['fall_origin_x']=target['x']
                    events.append({'move':'disaster','event':'fall','tick':tick,
                                   'after_status':status,'target':target['name']})
                lift=0
                if target['status'] in ['fall','down']:
                    fall_age=tick-target['fall_tick']
                    target['x']=target['fall_origin_x']+min(fall_age,6)*3
                    pose=16 if fall_age<3 else 17 if fall_age<6 else 18
                    lift=[0,4,7,9,7,4,0][min(fall_age,6)]
                    if fall_age>=6:target['status']='down'
                else:
                    pose=36 if target['status']=='burn' else 42 if target['status']=='freeze' else 2
                assert pose in [2,16,17,18,36,42]
                if target['hits']:assert pose!=2
                reaction_log.append({'tick':tick,'target':target['name'],'status':target['status'],'pose':pose})
                stage.alpha_composite(actor(original[target['name']],pose,True),
                                      (round(target['x'])-12,round(target['y'])-24-lift))
            for shot in projectiles:
                if not shot['hit']:
                    sprite=effect((41 if shot['kind']=='fire' else 49)+(tick//2)%2)
                    if shot['vx']<0:sprite=sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    stage.alpha_composite(sprite,(round(shot['x'])-8,round(shot['y'])-18))
            for impact in impacts:
                age=tick-impact['tick']
                if 0<=age<6:
                    n=([46,47,48] if impact['kind']=='fire' else [50,51,52])[age//2]
                    stage.alpha_composite(effect(n),(impact['x'],impact['y']))
            emit(stage,delay,'OVERWHELMING DISASTER')
        assert len(projectiles)==4 and [s['kind'] for s in projectiles]==order
        assert [s['lane'] for s in projectiles]==launch_lanes
        assert len(disaster_hits)==4,('Unhit disaster balls',projectiles)
        assert all(target['status']=='down' for target in targets)
        section_stats['disaster']={'order':order,'launch_lanes':launch_lanes,'spawn_ticks':spawn_ticks,'one_projectile_per_emission':True,'recovery_frames':[16,17,18],'recovery_behavior':'burn/freeze -> fall -> remain on ground','reaction_timeline':reaction_log,'hit_effects':['burn','freeze','burn','freeze'],'frames':len(frames)-before,'duration_ms':6500,'steering':'Julian-style enemy targeting, X acceleration2/clamp17, depth acceleration1/clamp3; motion scaled for this mockup'}

        # Arctic Volcano: native Freeze spin -> native Firen explosion, no gap.
        before=len(frames);center=146;ground=138;origin=ground-24
        fixed_poses={}
        for n in [111,112,113,114,93]:
            j=n-61;x=j%12*26+1;y=j//12*26+1
            mapping=({84:83,82:81,7:66,6:77,109:11,110:10,132:hair[0],134:hair[1],121:31}
                     if n!=93 else {82:83,145:66,146:77,67:11,68:10,77:hair[0],78:hair[1],117:31})
            fixed_poses[n]=m.indexed([mapping.get(v,v) for v in m.crop_pixels(raw2,(x,y,x+25,y+25))],(25,25),pal).convert('RGBA')
        explosions=[m.indexed(m.crop_pixels(weapons,(x,81,x+35,110)),(35,29),pal).convert('RGBA') for x in [163,199,235]]
        start_spin=8;end_spin=32
        volcano_targets=[{'name':'davis','side':-1,'x':center-20,'frozen':False},
                         {'name':'woody','side':1,'x':center+20,'frozen':False}]
        for t,delay in frame_samples(4300,fps):
            tick=round(t*fps/1000);stage=bg.copy()
            if tick<start_spin:caster=actor(firzen,2 if tick<5 else 35)
            elif tick<end_spin:caster=fixed_poses[111+((tick-start_spin)//2)%4]
            elif tick<end_spin+6:caster=fixed_poses[93]
            else:caster=actor(firzen,2)
            stage.alpha_composite(caster,(center-12,origin))
            for target in volcano_targets:
                side=target['side'];x=target['x'];lift=0
                if start_spin<=tick<end_spin:
                    # Contact freezes the target in place; there is no pull.
                    if abs(x-center)<=24 and not target['frozen']:
                        target['frozen']=True
                        events.append({'move':'arctic_volcano','event':'freeze','tick':tick,
                                       'target':target['name'],'x':x})
                    pose=42 if target['frozen'] else 2
                elif tick>=end_spin:
                    age=tick-end_spin
                    if age==0:
                        events.append({'move':'arctic_volcano','event':'burn_knockback','tick':tick,
                                       'target':target['name'],'was_frozen':target['frozen'],'x':x})
                    # Reuse the native burning sprite during airborne knockback.
                    x+=side*min(age,6)*3
                    pose=36 if age<6 else 18
                    lift=[0,4,7,9,7,4,0][min(age,6)]
                else:pose=2
                stage.alpha_composite(actor(original[target['name']],pose,side>0),
                                      (round(x)-12,origin-lift))
            if end_spin<=tick<end_spin+6:
                stage.alpha_composite(explosions[(tick-end_spin)//2],(center-17,ground-27))
            emit(stage,delay,'ARCTIC VOLCANO')
        assert all(target['frozen'] for target in volcano_targets)
        section_stats['arctic_volcano']={'spin_frames':[111,112,113,114],'spin_ticks':24,'explosion_pose':93,'explosion_crops':[[x,81,35,29] for x in [163,199,235]],'gap_ticks':0,'spin_effect':'freeze on contact','pulls_targets':False,'explosion_effect':'ignite and knock back frozen targets','frames':len(frames)-before,'duration_ms':4300}

    args.output.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(args.output,save_all=True,append_images=frames[1:],duration=durations,loop=0,optimize=False,disposal=1)
    meta={'scope':'Research mockup only; no game executables or data patched','canvas_native':[320,180],'canvas_preview':[1280,720],'scale':4,'fps':fps,'hair_pair':hair,'shirt':[66,77],'trousers':[11,10],'palette_source':'SYS/PAL fixed1..150; no custom colors','sections':section_stats,'events':events,'duration_ms':sum(durations)}
    args.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    assert original_hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in game_paths}
    assert hair==[args.hair_highlight,args.hair_shadow]
    with Image.open(args.output) as gif:
        assert gif.size==(1280,720) and gif.info['loop']==0
        elapsed=0
        for i in range(gif.n_frames):gif.seek(i);elapsed+=gif.info['duration']
        assert elapsed==sum(durations)
        print(f'Saved {args.output}: {gif.n_frames} frames, all three moves, 4 elemental hits, no game-file changes.')


if __name__=='__main__':main()

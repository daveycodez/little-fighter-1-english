#!/usr/bin/env python3
"""LF1 Road combat mockup: Firzen Cannon hits and knocks down Julian.

Native canvas 320x180, exactly 16:9; final preview 4x nearest-neighbor.
All character poses, background, and impact effects use original LF1 assets.
The Cannon is user-approved art. Collision/recoil timing is illustrative,
not an implemented gameplay patch or a capture of the running DOS game.
"""
from pathlib import Path
import argparse,hashlib,json,math
from PIL import Image
from render_character_preview import load_palette,read_grh,indexed,crop_pixels,original_characters,render_character,color_pair
from render_blast_preview import frame_samples


def road_background(root,palette):
    source=read_grh(root/'SYS/BACK31.GRH');source.putpalette(palette)
    source=source.convert('RGB')
    stage=Image.new('RGB',(320,180))
    stage.paste(source.crop((0,0,320,134)),(0,0))
    # Insert 36 native rows of the existing flat road before its lower border.
    for y in range(36):
        stage.paste(source.crop((0,112+y%22,320,113+y%22)),(0,134+y))
    stage.paste(source.crop((0,134,320,144)),(0,170))
    return stage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--speed',type=float,default=100)
    parser.add_argument('--shot-ticks',type=int,default=3)
    parser.add_argument('--hold-seconds',type=float,default=2)
    parser.add_argument('--fps',type=float,default=18.2)
    parser.add_argument('--post-release-ms',type=int,default=2300,help='Continue projectile travel after firing stops.')
    parser.add_argument('--head',type=Path,default=Path('art/firzen/firzen-head-gameplay-v50.png'))
    parser.add_argument('--hair',type=int,choices=range(1,151),default=98)
    parser.add_argument('--shirt',type=color_pair,default=[66,77])
    parser.add_argument('--trousers',type=color_pair,default=[11,10])
    parser.add_argument('--output',type=Path,default=Path('art/previews/firzen-cannon-vs-julian-road-16x9-4x.gif'))
    args=parser.parse_args()
    if args.speed<=0 or args.shot_ticks<1 or not 0<args.fps<=100 or args.hold_seconds<=0 or args.post_release_ms<=0 or args.post_release_ms%10:
        parser.error('Use positive speed, cadence, hold duration and FPS <=100.')
    root=Path(__file__).resolve().parent.parent;palette=load_palette(root)
    background=road_background(root,palette)
    originals=original_characters(root)
    firzen={'name':'Firzen','skin':[83,81],'shirt':args.shirt,'trousers':args.trousers,'hair':args.hair}
    head=args.head if args.head.is_absolute() else root/args.head
    attacker={n:render_character(root,palette,firzen,n,head)[0].convert('RGBA') for n in [2,35,43]}
    julian={n:render_character(root,palette,originals['julian'],n)[0].convert('RGBA').transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            for n in [2,14,15,16,17,18]}
    weapons=read_grh(root/'SYS/WEAPON.GRH')
    effects={}
    for n in [46,47,48]:
        x=(n-1)%15*18+1;y=(n-1)//15*14+1
        effects[n]=indexed(crop_pixels(weapons,(x,y,x+17,y+13)),(17,13),palette).convert('RGBA')
    projectile_paths={'lead':root/'art/firzen/firzen-ball-v2.png',
                      'segment':root/'art/firzen/firzen-cannon-segment-v4.png'}
    projectiles={k:Image.open(p).convert('RGBA') for k,p in projectile_paths.items()}
    hold_ms=round(args.hold_seconds*1000)
    if hold_ms%10:parser.error('GIF hold duration must be a multiple of 10ms.')
    timeline=[('idle',0,450),('windup',0,180)]
    timeline += [('hold',t,d) for t,d in frame_samples(hold_ms,args.fps)]
    timeline += [('release',t+hold_ms,d) for t,d in frame_samples(args.post_release_ms,args.fps)]
    timeline += [('pause',hold_ms+args.post_release_ms,700)]
    firzen_x=70;ground_y=138;origin_y=ground_y-24;beam_y=origin_y+13;spawn_x=firzen_x+25
    julian_x=188;push=0;fall_tick=None;last_hit_tick=None
    shots=[];impacts=[];hit_events=[];render_log=[]
    frames=[];durations=[];impact_preview=None;fall_preview=None
    colors={tuple(palette[i*3:i*3+3]):i for i in reversed(range(151))}
    frame_palette=palette[:]
    for phase,elapsed,delay in timeline:
        clock_tick=round(elapsed*args.fps/1000)
        firing=phase=='hold'
        if firing and clock_tick%args.shot_ticks==0:
            shots.append({'kind':'lead' if clock_tick==0 else 'segment',
                          'born_ms':elapsed,'born_tick':clock_tick,'hit':False})
        if fall_tick is None:
            age=clock_tick-last_hit_tick if last_hit_tick is not None else 999
            target_pose=14 if age<2 else 15 if age<4 else 2
            target_x=julian_x+push;lift=0
        else:
            age=max(0,clock_tick-fall_tick)
            target_pose=16 if age<3 else 17 if age<6 else 18
            target_x=julian_x+push+min(age,6)*3
            lift=[0,4,7,9,7,4,0][min(age,6)]
        target=julian[target_pose]
        target_y=origin_y-lift
        box=target.getchannel('A').getbbox()
        collision_left=target_x+box[0]
        active=[]
        for shot in shots:
            if shot['hit']:continue
            x=spawn_x+round(args.speed*(elapsed-shot['born_ms'])/1000)
            effect=projectiles[shot['kind']]
            if fall_tick is None and phase not in ['idle','windup'] and x+effect.width>=collision_left:
                shot['hit']=True;last_hit_tick=clock_tick
                impacts.append({'tick':clock_tick,'x':collision_left-8,'y':beam_y-6})
                hit_events.append({'tick':clock_tick,'time_ms':elapsed,'shot_tick':shot['born_tick']})
                push+=3;target_x=julian_x+push;target_pose=14;target=julian[target_pose]
                if len(hit_events)==3:
                    fall_tick=clock_tick;target_pose=16;target=julian[target_pose]
                continue
            if x<320:
                active.append((shot['kind'],effect,x))
        stage=background.convert('RGBA')
        attack_pose=43 if firing else 35 if phase=='windup' or (phase=='release' and elapsed-hold_ms<110) else 2
        stage.alpha_composite(attacker[attack_pose],(firzen_x,origin_y))
        stage.alpha_composite(target,(target_x,target_y))
        for kind,effect,x in sorted(active,key=lambda item:item[0]=='lead'):
            stage.alpha_composite(effect,(x,beam_y-effect.height//2))
        impact_active=False
        for hit in impacts:
            age=clock_tick-hit['tick']
            if 0<=age<6:
                stage.alpha_composite(effects[[46,47,48][age//2]],(hit['x'],hit['y']))
                impact_active=True
        rgb=stage.convert('RGB')
        native=Image.new('P',rgb.size);native.putpalette(frame_palette)
        native.putdata([colors[p] for p in rgb.get_flattened_data()])
        assert native.convert('RGB').tobytes()==rgb.tobytes()
        frame=native.resize((1280,720),Image.Resampling.NEAREST)
        frames.append(frame);durations.append(delay)
        if impact_active and impact_preview is None:impact_preview=frame.convert('RGB')
        if target_pose==18 and fall_preview is None:fall_preview=frame.convert('RGB')
        render_log.append({'phase':phase,'elapsed_ms':elapsed,'tick':clock_tick,'duration_ms':delay,
                           'julian_pose':target_pose,'julian_position':[target_x,target_y],
                           'firzen_pose':attack_pose,'visible_projectiles':len(active)})
    assert len(hit_events)==3 and fall_tick is not None
    assert impact_preview is not None and fall_preview is not None
    assert sum(d for phase,_,d in timeline if phase=='hold')==hold_ms
    args.output.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(args.output,save_all=True,append_images=frames[1:],duration=durations,
                   loop=0,optimize=False,disposal=1)
    impact_path=args.output.with_name(args.output.stem+'-impact.png')
    fall_path=args.output.with_name(args.output.stem+'-knockdown.png')
    impact_preview.save(impact_path);fall_preview.save(fall_path)
    meta={'purpose':'offline LF1 combat mockup; gameplay not implemented',
          'native_canvas':[320,180],'preview_canvas':[1280,720],'aspect_ratio':'16:9','scale':4,
          'background':'SYS/BACK31.GRH; 36 road rows inserted without rescaling',
          'firzen':firzen,'julian':originals['julian'],'julian_frames':[2,14,15,16,17,18],
          'impact_source':'SYS/WEAPON.GRH','impact_frames':[46,47,48],
          'fps':args.fps,'projectile_speed_pixels_per_second':args.speed,
          'shot_interval_ticks':args.shot_ticks,'hold_ms':hold_ms,'post_release_ms':args.post_release_ms,
          'hit_events':hit_events,'fall_tick':fall_tick,'timeline':render_log,
          'projectile_hashes':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in projectile_paths.items()},
          'palette_colors_exact':True,'gif_duration_ms':sum(durations)}
    args.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    with Image.open(args.output) as gif:
        assert gif.size==(1280,720) and gif.info['loop']==0
        decoded_ms=0
        for n in range(gif.n_frames):
            gif.seek(n);decoded_ms+=gif.info['duration']
        assert decoded_ms==sum(durations)
        print(f'Saved {args.output}: {gif.n_frames} frames, three impacts, Julian falling, exact 16:9 at 4x.')


if __name__=='__main__':main()

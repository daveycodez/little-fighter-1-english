#!/usr/bin/env python3
"""Animate a casting mockup with native LF1 poses and an unchanged projectile.

python3 -B export/render_blast_preview.py --name Firzen \
  --head art/firzen/firzen-head-gameplay-v50.png --skin 83,81 \
  --shirt 67,68 --trousers 132,134 --hair 98 \
  --projectile art/firzen/firzen-ball-v2.png \
  --segment art/firzen/firzen-cannon-segment-v4.png --hold-seconds 2 \
  --fps 18.2 --shot-interval-ticks 4 \
  --output art/previews/firzen-cannon-mockup-4x.gif

Frames 35 and 43 are shared baked-head windup/release poses. Timing, travel,
and attachment placement are illustrative, not implemented gameplay logic.
No native asset is scaled; only the finished preview is enlarged exactly 4x.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image
from render_character_preview import color_pair, load_palette, original_characters, render_character


def frame_samples(duration_ms, fps):
    """Sample at a fixed clock; GIF centisecond rounding preserves total time."""
    for n in range(math.ceil(duration_ms*fps/1000)):
        elapsed=n*1000/fps
        end=min((n+1)*1000/fps,duration_ms)
        delay=round(end/10)*10-round(elapsed/10)*10
        if delay:
            yield elapsed,delay


def make_timeline(hold_ms,shot_interval_ticks,fps,speed,continuing=True):
    """Emit every N game ticks; sampling and travel speed stay independent."""
    timeline=[{'pose':2,'effects':[],'duration':450},
              {'pose':35,'effects':[],'duration':180}]
    shots=[{'kind':'lead','tick':0,'time_ms':0}]
    if continuing:
        shots += [{'kind':'segment','tick':tick,'time_ms':tick*1000/fps}
                  for tick in range(shot_interval_ticks,math.ceil(hold_ms*fps/1000),shot_interval_ticks)]

    def effects_at(elapsed):
        effects=[]
        for shot in shots:
            if shot['time_ms']<=elapsed:
                x=33+round(speed*(elapsed-shot['time_ms'])/1000)
                if x<140:
                    effects.append({'kind':shot['kind'],'x':x})
        return effects

    for elapsed,delay in frame_samples(hold_ms,fps):
        timeline.append({'pose':43,'effects':effects_at(elapsed),'duration':delay,
                         'phase':'hold','tick':round(elapsed*fps/1000),'elapsed_ms':elapsed})
    # Release stops spawning; shots already emitted keep their original speed.
    for elapsed,delay in frame_samples(1200,fps):
        timeline.append({'pose':35 if elapsed<100 else 2,
                         'effects':effects_at(hold_ms+elapsed),'duration':delay,
                         'phase':'release','elapsed_ms':elapsed})
    timeline.append({'pose':2,'effects':[],'duration':600})
    return timeline,shots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--name', default='Firzen')
    parser.add_argument('--head', type=Path)
    parser.add_argument('--skin', type=color_pair)
    parser.add_argument('--shirt', type=color_pair)
    parser.add_argument('--trousers', type=color_pair)
    parser.add_argument('--hair', type=int, choices=range(1,151))
    parser.add_argument('--projectile', type=Path, required=True)
    parser.add_argument('--segment', type=Path, help='Additional projectile used while holding the Cannon.')
    parser.add_argument('--hold-seconds', type=float, default=2.0)
    parser.add_argument('--fps', type=float, default=18.2, help='Fixed preview update rate.')
    parser.add_argument('--shot-interval-ticks', type=int, default=4, help='Emit one shot every N game ticks; never changes the frame clock.')
    parser.add_argument('--projectile-speed', type=float, default=160, help='Fixed projectile travel speed in native pixels per second.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.hold_seconds<=0:
        parser.error('--hold-seconds must be positive.')
    if not 0<args.fps<=100 or args.shot_interval_ticks<=0 or args.projectile_speed<=0:
        parser.error('Use FPS in (0,100] and positive shot interval and projectile speed.')
    palette = load_palette(args.game_root)
    originals = original_characters(args.game_root)
    record = dict(originals.get(args.name.casefold(), {'name': args.name}))
    for field in ['skin', 'shirt', 'trousers', 'hair']:
        if getattr(args, field) is not None:
            record[field] = getattr(args, field)
    if not all(field in record for field in ['skin','shirt','trousers','hair']):
        parser.error('A custom fighter needs --head, --skin, --shirt, --trousers and --hair.')
    if 'head_id' not in record and args.head is None:
        parser.error('A custom fighter needs --head.')
    poses = {}; pose_metadata = {}
    for frame in [2,35,43]:
        sprite, _, meta = render_character(args.game_root,palette,record,frame,args.head)
        poses[frame] = sprite.convert('RGBA'); pose_metadata[frame] = meta
    projectile = Image.open(args.projectile).convert('RGBA')
    projectile_hash = hashlib.sha256(args.projectile.read_bytes()).hexdigest()
    segment = Image.open(args.segment).convert('RGBA') if args.segment else None
    if segment and segment.width!=projectile.width:
        parser.error('Lead and continuing segment must have equal native widths.')
    if segment and {c[:3] for c in segment.get_flattened_data() if c[3]}!={c[:3] for c in projectile.get_flattened_data() if c[3]}:
        parser.error('Lead and continuing segment must have the same colors.')
    # Keep game colors and the concept projectile's LF2 colors exactly in the GIF.
    colors = list(dict.fromkeys(tuple(palette[i*3:i*3+3]) for i in range(151)))
    for effect in [projectile]+([segment] if segment else []):
        colors += [c[:3] for c in effect.get_flattened_data() if c[3] and c[:3] not in colors]
    colors = list(dict.fromkeys(colors + [(48,48,48), (96,96,96)]))
    if len(colors)>256:
        raise ValueError('Preview colors exceed GIF palette capacity.')
    gif_palette = Image.new('P',(1,1))
    gif_palette.putpalette([v for color in colors for v in color] + [0]*(768-len(colors)*3))
    color_indices = {color:index for index,color in enumerate(colors)}
    hold_ms=round(args.hold_seconds*1000)
    if hold_ms%10:
        parser.error('GIF hold duration must be a multiple of 10ms.')
    timeline,shots=make_timeline(hold_ms,args.shot_interval_ticks,args.fps,
                                 args.projectile_speed,continuing=segment is not None)
    frames = []; durations = []; release = None
    for step_index,step in enumerate(timeline):
        pose=step['pose'];duration=step['duration']
        stage = Image.new('RGBA',(140,41),(48,48,48,255))
        stage.alpha_composite(poses[pose],(8,8))
        # Center both kinds at the release pose's right palm (native y=21).
        # Draw the rounded lead last, keeping its silhouette intact.
        for particle in sorted(step['effects'],key=lambda p:p['kind']=='lead'):
            effect=projectile if particle['kind']=='lead' else segment
            stage.alpha_composite(effect,(particle['x'],21-effect.height//2))
        preview = stage.convert('RGB').resize((560,164),Image.Resampling.NEAREST)
        if pose==43 and (release is None or (segment and step_index==12)):
            release=preview.copy()
        frame = Image.new('P',preview.size)
        frame.putpalette(gif_palette.getpalette())
        frame.putdata([color_indices[c] for c in preview.get_flattened_data()])
        if frame.convert('RGB').tobytes()!=preview.tobytes():
            raise ValueError('GIF quantization changed preview colors.')
        frames.append(frame);durations.append(duration)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(args.output,save_all=True,append_images=frames[1:],duration=durations,
                   loop=0,optimize=False,disposal=2)
    still = args.output.with_name(args.output.stem.replace('-mockup','-release')+'.png')
    release.save(still)
    # Show the unchanged native release frame separately for reuse.
    native = args.output.with_name(args.output.stem.replace('-mockup-4x','-casting-native')+'.png')
    poses[43].save(native)
    meta = {'purpose':'offline animation mockup; not game implementation',
            'character':record, 'poses':pose_metadata,'scale':4,'scaling':'nearest neighbor',
            'native_stage_size':[140,41], 'projectile_size':list(projectile.size),
            'projectile':str(args.projectile.resolve()),'projectile_sha256':projectile_hash,
            'projectile_changed':False, 'gif_colors_exact':True,
            'timing_and_travel':'illustrative', 'timeline':timeline,
            'hold_ms':hold_ms if segment else None,
            'preview_fps':args.fps,
            'gif_frame_timing':'Fixed-rate samples rounded cumulatively to GIF 10ms units',
            'projectile_speed_pixels_per_second':args.projectile_speed,
            'emission_interval_ticks':args.shot_interval_ticks if segment else None,
            'emission_interval_ms':args.shot_interval_ticks*1000/args.fps if segment else None,
            'emissions':shots,
            'segment':str(args.segment.resolve()) if args.segment else None,
            'segment_size':list(segment.size) if segment else None,
            'requested_gameplay':'Continue firing until cancelled or mana is exhausted; mockup demonstrates cancellation after hold.',
            'outputs':{'animation':str(args.output.resolve()),'release':str(still.resolve()),
                       'casting_native':str(native.resolve())}}
    args.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    with Image.open(args.output) as check:
        assert check.size==(560,164) and check.info.get('loop')==0
        expected_runs = 1+sum(frames[i].tobytes()!=frames[i-1].tobytes() for i in range(1,len(frames)))
        assert check.n_frames==expected_runs
        decoded_duration=0
        for i in range(check.n_frames):
            check.seek(i);decoded_duration+=check.info['duration']
        assert decoded_duration==sum(durations)
    if segment:
        assert sum(step['duration'] for step in timeline if step['pose']==43)==hold_ms
    print(f'Saved {args.output}, {still}; head skipped on frames 35/43, hair recolored.')


if __name__=='__main__':
    main()

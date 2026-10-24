"""Replace only the revised 66–72s shot, then add narration to approved exports."""
from pathlib import Path
import json, shutil, subprocess, sys

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'output' / 'orb-product-demo'
FFMPEG = shutil.which('ffmpeg')
FFPROBE = shutil.which('ffprobe')
assert FFMPEG and FFPROBE, 'Existing full FFmpeg and FFprobe are required.'
orientations = sys.argv[1:] or ['landscape', 'portrait']
for orientation in orientations:
    assert orientation in ('landscape', 'portrait')
    dimensions = '1920x1080' if orientation == 'landscape' else '1080x1920'
    destination = OUT / f'Orb-Product-Demo-{dimensions}.mp4'
    approved = OUT / 'work' / f'approved-{orientation}.mp4'
    patch = OUT / 'work' / f'Orb-Architecture-{orientation}.mp4'
    info = json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_entries',
                     'stream=nb_frames,r_frame_rate', '-of', 'json', str(patch)]))
    video = info['streams'][0]
    assert video['nb_frames'] == '180' and video['r_frame_rate'] == '30/1'
    if not approved.exists():
        shutil.copy2(destination, approved)
    temporary = OUT / 'work' / f'narrated-{orientation}.mp4'
    filters = ('[0:v]split=2[basehead][basetail];'
               '[basehead]trim=start_frame=0:end_frame=1980,setpts=PTS-STARTPTS[head];'
               '[1:v]setpts=PTS-STARTPTS[patch];'
               '[basetail]trim=start_frame=2160:end_frame=2880,setpts=PTS-STARTPTS[tail];'
               '[head][patch][tail]concat=n=3:v=1:a=0[v]')
    subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'warning', '-stats', '-y',
                    '-threads', '2', '-i', str(approved), '-threads', '2', '-i', str(patch),
                    '-i', str(HERE / 'public' / 'orb-narrated-mix.wav'),
                    '-filter_complex_threads', '2', '-filter_complex', filters,
                    '-map', '[v]', '-map', '2:a:0', '-c:v', 'libx264', '-crf', '16',
                    '-preset', 'medium', '-threads', '4', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '320k', '-t', '96', '-movflags', '+faststart',
                    '-metadata', 'title=Orb — Perceive. Remediate. Decode.',
                    '-metadata', 'comment=Orb AI; English synthetic narration; original score; approved edit with revised architecture shot.',
                    str(temporary)], check=True)
    temporary.replace(destination)
    print(f'Updated {destination.name}', flush=True)

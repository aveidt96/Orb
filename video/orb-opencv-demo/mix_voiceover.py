"""Fit offline narration to reviewed shots and duck the existing original score."""
from pathlib import Path
import json, shutil, subprocess, wave
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'output' / 'orb-product-demo'
WORK = OUT / 'work' / 'voiceover'
PUBLIC = HERE / 'public'
FFMPEG = shutil.which('ffmpeg')
if not FFMPEG:
    raise SystemExit('The existing full FFmpeg installation is required to mix narration.')
SR = 48000
timeline = json.loads((HERE / 'timeline.json').read_text(encoding='utf-8'))
script = json.loads((HERE / 'narration.json').read_text(encoding='utf-8'))
samples = timeline['duration'] * SR
narration = np.zeros(samples, dtype=np.float64)
duck = np.ones(samples, dtype=np.float64)
report = {'voice': json.loads((WORK / 'voice.json').read_text(encoding='utf-8-sig')), 'cues': []}

def decode(path, tempo=1):
    args = [str(FFMPEG), '-v', 'error', '-i', str(path)]
    if tempo != 1:
        args += ['-af', f'atempo={tempo:.8f}']
    return np.frombuffer(subprocess.check_output(args + ['-f', 'f32le', '-ar', str(SR), '-ac', '1', '-']), dtype='<f4').astype(np.float64)

def save(path, audio):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1 if audio.ndim == 1 else audio.shape[1])
        output.setsampwidth(2)
        output.setframerate(SR)
        output.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())

previous_end = 0
for cue in script['cues']:
    assert previous_end <= cue['start'] < cue['end'] <= timeline['duration'], cue['id']
    previous_end = cue['end']
    source = WORK / (cue['id'] + '.wav')
    voice = decode(source)
    # Remove synthesis padding, retaining short natural leading/trailing breaths.
    audible = np.flatnonzero(np.abs(voice) > .003)
    assert audible.size, f"Empty narration: {cue['id']}"
    first = max(0, audible[0] - round(.035 * SR))
    last = min(len(voice), audible[-1] + round(.08 * SR))
    voice = voice[first:last]
    available = cue['end'] - cue['start']
    raw_duration = len(voice) / SR
    tempo = max(1, raw_duration / (available - .08))
    if tempo > 1.18:
        raise ValueError(f"Shorten {cue['id']} narration: needs {tempo:.2f}x speed")
    if tempo > 1:
        trimmed = WORK / (cue['id'] + '-trimmed.wav')
        save(trimmed, voice)
        voice = decode(trimmed, tempo)
    assert len(voice) / SR <= available, cue['id']
    rms = np.sqrt(np.mean(voice ** 2))
    voice *= min(10 ** (-19 / 20) / max(rms, .00001), .82 / np.max(np.abs(voice)))
    fade = min(round(.012 * SR), len(voice) // 2)
    voice[:fade] *= np.linspace(0, 1, fade)
    voice[-fade:] *= np.linspace(1, 0, fade)
    start = round(cue['start'] * SR)
    end = start + len(voice)
    narration[start:end] = voice
    # Keep interface sounds audible; music sits 15 dB below its original level under speech.
    floor = .18
    duck[start:end] = np.minimum(duck[start:end], floor)
    attack = min(round(.18 * SR), start)
    release = min(round(.35 * SR), samples - end)
    duck[start-attack:start] = np.minimum(duck[start-attack:start], np.linspace(1, floor, attack))
    duck[end:end+release] = np.minimum(duck[end:end+release], np.linspace(floor, 1, release))
    report['cues'].append({'id': cue['id'], 'start': cue['start'], 'end': round(end / SR, 4),
                           'window_end': cue['end'], 'tempo': round(tempo, 4), 'text': cue['text']})

with wave.open(str(PUBLIC / 'orb-original-score.wav')) as source:
    assert source.getframerate() == SR and source.getnchannels() == 2 and source.getsampwidth() == 2
    score = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').reshape(-1, 2).astype(np.float64) / 32768
assert len(score) == samples
mix = score * (duck * .65)[:, None] + narration[:, None]
peak = float(np.max(np.abs(mix)))
mix *= min(1, .94 / max(peak, .00001))
save(PUBLIC / 'orb-voiceover.wav', narration)
save(PUBLIC / 'orb-narrated-mix.wav', mix)
report.update({'duration_seconds': timeline['duration'], 'sample_rate': SR, 'mix_peak_dbfs': round(20*np.log10(np.max(np.abs(mix))), 2)})
(PUBLIC / 'narration-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
(OUT / 'Voiceover-Script.txt').write_text('\n\n'.join(f"{c['start']:05.1f}s — {c['text']}" for c in script['cues']) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))

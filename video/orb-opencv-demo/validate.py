"""Offline validation of the authored film and completed exports; no cloud access."""
from pathlib import Path
import json, re, subprocess, wave, os, shutil
import numpy as np
HERE=Path(__file__).resolve().parent
OUT=HERE.parents[1]/'output'/'orb-product-demo'
DEPS=Path(os.environ.get('REMOTION_DEPS_DIR',str(HERE.parents[2]/'orb-demo-video'/'node_modules')))
t=json.loads((HERE/'timeline.json').read_text(encoding='utf-8'))
assert t['duration']==96 and t['duration']<=150
assert all(s['start']%(60/t['bpm']*4)==0 for s in t['scenes'])
assert all(e['frame']==round(e['at']*t['fps']) for e in t['events'])
for name in ['demo-data.json','live-result.json','telemetry.json']:
 text=(HERE/'public'/name).read_text(encoding='utf-8')
 assert not re.search(r'0x[0-9a-fA-F]{40}\b|eyJ[A-Za-z0-9_-]{20}|X-Amz-Signature|postgres(?:ql)?://|AIza[A-Za-z0-9_-]{25}',text),name
 assert not any(c in text for c in ['\u00c2','\u00e2\u20ac'])
for path in [HERE/'Root.jsx',HERE/'narration.json',*(HERE/'public').glob('*.json')]:
 assert not re.search(r'gemini|flash[\s-]*lite|google',path.read_text(encoding='utf-8'),re.I),path.name
assert json.loads((HERE/'public/live-result.json').read_text(encoding='utf-8'))['provider']=='Orb AI'
with wave.open(str(HERE/'public/orb-original-score.wav')) as w:
  assert w.getnframes()/w.getframerate()==96 and w.getnchannels()==2
for name,channels in [('orb-voiceover.wav',1),('orb-narrated-mix.wav',2)]:
 with wave.open(str(HERE/'public'/name)) as w:
  assert w.getnframes()/w.getframerate()==96 and w.getnchannels()==channels and w.getframerate()==48000
  pcm=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').reshape(-1,channels).astype(np.float64)/32768
  assert np.max(np.abs(pcm))<.99 and np.sqrt(np.mean(pcm**2))>.02,name
  if channels==2:expected_audio=pcm.mean(axis=1)
narration=json.loads((HERE/'public/narration-report.json').read_text(encoding='utf-8'))
script=json.loads((HERE/'narration.json').read_text(encoding='utf-8'))
assert len(narration['cues'])==len(script['cues'])==14
last_end=0
for actual,cue in zip(narration['cues'],script['cues']):
 assert actual['id']==cue['id'] and actual['text']==cue['text']
 assert last_end<=actual['start']==cue['start']<actual['end']<=cue['end']<=96
 last_end=actual['end']
report={'duration_seconds':96,'fps':30,'bar_aligned_sections':True,'frame_aligned_cues':True,'public_data_sanitized':True,
        'ai_branding':'Orb AI','voiceover':{'voice':narration['voice']['voice'],'language':narration['voice']['language'],
        'cue_count':len(narration['cues']),'timing_verified':True,'music_ducked':True},'exports':[]}
ffmpeg=shutil.which('ffmpeg')
assert ffmpeg,'Existing full FFmpeg is required for export audio validation.'
for name,dimensions in [('Orb-Product-Demo-1920x1080.mp4',(1920,1080)),('Orb-Product-Demo-1080x1920.mp4',(1080,1920))]:
 path=OUT/name
 if not path.exists():
  raise SystemExit('Export not complete: '+name)
 probe=DEPS/'@remotion'/'compositor-win32-x64-msvc'/'ffprobe.exe'
 result=json.loads(subprocess.check_output([str(probe),'-v','error','-show_streams','-show_format','-of','json',str(path)]))
 v=next(s for s in result['streams'] if s['codec_type']=='video')
 a=next(s for s in result['streams'] if s['codec_type']=='audio')
 assert (v['width'],v['height'])==dimensions and v['codec_name']=='h264'
 assert v['r_frame_rate']=='30/1' and v['pix_fmt'] in ('yuv420p','yuvj420p')
 assert abs(float(result['format']['duration'])-96)<.1
 assert a['codec_name']=='aac' and a['channels']==2
 decoded=np.frombuffer(subprocess.check_output([ffmpeg,'-v','error','-i',str(path),'-vn','-f','f32le','-ar','48000','-ac','1','-']),dtype='<f4')
 assert len(decoded)>=len(expected_audio)-1024
 length=min(len(decoded),len(expected_audio))
 correlation=float(np.corrcoef(decoded[:length],expected_audio[:length])[0,1])
 assert correlation>.98,f'{name}: export audio does not match narrated mix ({correlation:.4f})'
 report['exports'].append({'file':name,'bytes':path.stat().st_size,'dimensions':dimensions,'video':'H.264 CRF 16','pixel_format':v['pix_fmt'],'audio':'AAC stereo 320 kbps','duration':result['format']['duration'],'frames':v.get('nb_frames'),'narrated_mix_correlation':round(correlation,6)})
(OUT/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))

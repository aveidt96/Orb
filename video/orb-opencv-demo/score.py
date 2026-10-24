from pathlib import Path
import json,math,wave
import numpy as np
HERE=Path(__file__).resolve().parent
PUBLIC=HERE/"public"
timeline=json.loads((HERE/"timeline.json").read_text(encoding="utf-8"))

# All musical synthesis and interface sounds share the visual timeline JSON.
SR=48000
duration=timeline['duration']
audio=np.zeros((duration*SR,2),dtype=np.float64)
rng=np.random.default_rng(2026)
def add(sound,at,vol=1,pan=0):
    start=round(at*SR); end=min(len(audio),start+len(sound))
    if end<=start:return
    s=sound[:end-start]*vol
    audio[start:end,0]+=s*math.sqrt((1-pan)*.5)
    audio[start:end,1]+=s*math.sqrt((1+pan)*.5)
def tone(freq,dur,decay=4,kind='sine'):
    t=np.arange(round(SR*dur))/SR
    env=(1-np.exp(-t*180))*np.exp(-t*decay)*np.minimum(1,(dur-t)*40)
    if kind=='bell': signal=np.sin(2*np.pi*freq*t+1.3*np.sin(2*np.pi*freq*2*t)*np.exp(-t*7))
    else: signal=np.sin(2*np.pi*freq*t)+.2*np.sin(2*np.pi*freq*2*t)
    return env*signal
def midi(n):return 440*2**((n-69)/12)
chords=[[50,57,62,65,69],[46,53,58,62,65],[53,60,65,69,72],[48,55,60,64,67]]
beat=60/timeline['bpm'];bar=beat*4
for b in range(round(duration/bar)):
    at=b*bar; chord=chords[(b//2)%4]
    for note in chord:
        add(tone(midi(note),2.6,decay=.7),at,.032,pan=(note%3-1)*.35)
    for eighth in range(8):
        note=chord[[0,2,3,4,2,1,3,2][eighth]]+12
        add(tone(midi(note),.45,decay=9,kind='bell'),at+eighth*beat/2,.06,pan=(-.45 if eighth%2 else .45))
    for k in range(4):
        t=np.arange(round(SR*.23))/SR
        kick=np.sin(2*np.pi*(43*t+42*.025*(1-np.exp(-t/.025))))*np.exp(-t*22)
        add(kick,at+k*beat,.25 if k%2==0 else .13)
        hat=rng.normal(0,1,round(SR*.06));hat=np.diff(hat,prepend=0)*np.exp(-np.arange(len(hat))/SR*80)
        add(hat,at+k*beat+.25,.025,pan=.3)
        if k in (1,3):
            snare=rng.normal(0,1,round(SR*.12))*np.exp(-np.arange(round(SR*.12))/SR*40)
            add(snare,at+k*beat,.035)
    add(tone(midi(chord[0]-12),1.7,decay=2),at,.12)
for event in timeline['events']:
    at=event['frame']/timeline['fps'];kind=event['type']
    if kind=='tap':add(tone(1050,.055,40),at,.18)
    elif kind=='typing':
        for j in range(event.get('characters',9)):
            offset=math.ceil((j+1)*event.get('durationFrames',18)/event.get('characters',9))/timeline['fps']
            add(tone(700+(j%3)*180,.035,65),at+offset,.045,pan=.15)
    elif kind in ('notification','incoming'):
        add(tone(880,.32,9,kind='bell'),at,.09);add(tone(1320,.38,9,kind='bell'),at+.085,.075)
    else:
        t=np.arange(round(SR*.21))/SR
        swoosh=rng.normal(0,1,len(t))*np.sin(np.pi*t/.21)**2*.02
        add(swoosh,at,.65);add(tone(660,.25,12),at,.08)
# Smooth opening/outro and normalize with conservative headroom.
fade=np.ones(len(audio));fade[:SR]=np.linspace(0,1,SR);fade[-2*SR:]=np.linspace(1,0,2*SR)
audio*=fade[:,None]
peak=float(np.max(np.abs(audio))); audio*=.78/max(peak,.001)
with wave.open(str(PUBLIC/'orb-original-score.wav'),'wb') as w:
    w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR);w.writeframes((audio*32767).astype('<i2').tobytes())
print('Original 120 BPM score and synchronized interface sounds generated.',flush=True)

"""Original media, real Orb CV artifacts, code-composed audio; no live AI calls."""
from pathlib import Path
import hashlib, json, math, shutil, sys, wave
import cv2
import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = HERE / 'public'
OUT = ROOT / 'output' / 'orb-product-demo'
WORK = OUT / 'work'
for directory in (PUBLIC, WORK, OUT / 'review'):
    directory.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from prometheus.analysis.opencv_telemetry import analyze_video_cv, _sharpness_and_geometry_metrics, _color_and_lighting_metrics

cv2.setNumThreads(1)
timeline = json.loads((HERE/'timeline.json').read_text(encoding='utf-8'))
source_files = ['web/index.html','web/styles.css','web/app.js','prometheus/analysis/opencv_telemetry.py','BENCHMARKS.md','SUBMISSION_GUIDE.md']
audit = {}
for name in source_files:
    text=(ROOT/name).read_text(encoding='utf-8')
    audit[name]={'sha256':hashlib.sha256(text.encode()).hexdigest(),'lines':len(text.splitlines())}
(OUT/'source-audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')

source=PUBLIC/'generated_scene.png'
if not source.exists():raise FileNotFoundError('The included original generated_scene.png is required')
bgr=cv2.imread(str(source))
base=cv2.resize(bgr,(1600,900),interpolation=cv2.INTER_AREA)
frames=[]
writer=cv2.VideoWriter(str(PUBLIC/'shadowed_corridor.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),30,(1280,720))
for i in range(180):
    x=round(260*(1-i/179))
    frame=base[90:810,x:x+1280].copy()
    writer.write(frame)
    if i%6==0:
        path=WORK/f'scene_{i:03}.jpg'
        cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,92])
        frames.append(path)
writer.release()
telemetry=analyze_video_cv(None,frame_paths=frames,output_dir=PUBLIC)
cv=telemetry.to_dict()
primary=cv['motion_and_continuity'].get('primary_keyframe')
if not primary:
    primary=cv['motion_and_continuity'].get('selected_keyframe')
ranking=cv['motion_and_continuity'].get('keyframe_ranking',[])
selected=max(frames,key=lambda p:_sharpness_and_geometry_metrics(cv2.imread(str(p)))['laplacian_sharpness'])
shutil.copyfile(selected,PUBLIC/'original_reference.jpg')
original=cv2.imread(str(selected))
recovered=cv2.imread(str(PUBLIC/'opencv_clahe_enhanced.jpg'))
before=_sharpness_and_geometry_metrics(original)
after=_sharpness_and_geometry_metrics(recovered)
cv['asset_provenance']={'source':'Original generated example scene','perception':'Actual repository OpenCV functions, local x86_64 run','vlm_output':'No VLM invoked by this local video telemetry example','before':before,'after':after}
(PUBLIC/'telemetry.json').write_text(json.dumps(cv,indent=2),encoding='utf-8')
print(json.dumps({'opencv':cv2.__version__,'mean_luminance':cv['color_and_lighting']['mean_luminance'],'clahe':cv['clahe_applied'],'motion':cv['motion_and_continuity'].get('dominant_motion'),'edge_before':before['edge_density_pct'],'edge_after':after['edge_density_pct']},indent=2),flush=True)

# The supplied video is a style/pacing reference only. No frame or audio is reused.
ref=Path('C:/Users/USER/Downloads/R_ThGS2vE2zPnzKp.mp4')
cap=cv2.VideoCapture(str(ref))
sheet=Image.new('RGB',(1440,880),'#eef7ff')
draw=ImageDraw.Draw(sheet)
for n,seconds in enumerate([0,8,20,40,65,90]):
    cap.set(cv2.CAP_PROP_POS_MSEC,seconds*1000)
    ok,frame=cap.read()
    if ok:
        im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)); im.thumbnail((700,394))
        x=(n%2)*720+10;y=(n//2)*293+25
        im.thumbnail((700,260));sheet.paste(im,(x,y))
        draw.text((x,y-18),f'Reference: {seconds}s',fill='#102747')
cap.release()
sheet.save(OUT/'review'/'reference-contact.jpg',quality=90)


import subprocess
subprocess.run([sys.executable,str(HERE/"score.py")],check=True)

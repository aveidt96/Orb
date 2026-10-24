"""Package only authored/sanitized source; never include .env, journals or runtime ledgers."""
from pathlib import Path
import json,shutil,zipfile
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'output'/'orb-product-demo'
report=json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
assert len(report['exports'])==2
shutil.copyfile(HERE/'README.md',OUT/'Production-Notes.md')
shutil.copyfile(HERE/'timeline.json',OUT/'Timeline.json')
shutil.copyfile(HERE/'public/orb-voiceover.wav',OUT/'Orb-Voiceover.wav')
with zipfile.ZipFile(OUT/'Orb-Remotion-Source.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for file in sorted(HERE.rglob('*')):
  if not file.is_file() or any(part in ['node_modules','__pycache__','.git'] for part in file.parts):continue
  assert file.name!='.env' and 'live-attempt' not in file.name
  z.write(file,file.relative_to(ROOT).as_posix())
 z.write(OUT/'source-audit.json','video/orb-opencv-demo/source-audit.json')
 z.write(OUT/'validation.json','video/orb-opencv-demo/export-validation.json')
 for name in ['Orb-Cover-landscape.png','Orb-Cover-portrait.png']:
  z.write(OUT/name,'covers/'+name)
print('Delivery source ZIP and provenance notes ready. No credentials or runtime journals included.')

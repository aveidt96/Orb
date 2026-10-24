from pathlib import Path
import json
HERE=Path(__file__).resolve().parent
public=HERE/'public'
live=json.loads((public/'live-result.json').read_text(encoding='utf-8'))
local=json.loads((public/'telemetry.json').read_text(encoding='utf-8'))
data={'live':True,'cv':live['opencv_telemetry'],'hud':'live_hud.jpg','clahe':'live_clahe.jpg',
      'summary':live.get('summary',''),'analysis':live.get('visual_analysis',{}),'prompt':live.get('prompt',''),
      'videoMotion':local['motion_and_continuity']}
(public/'demo-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Demo data uses the sanitized live AWS result and measured local optical flow.')

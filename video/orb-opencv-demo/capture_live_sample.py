"""One authorized judge Decode of original demo media; never retry media POSTs."""
from pathlib import Path
import json, sys, time, uuid
import requests

HERE=Path(__file__).resolve().parent
PUBLIC=HERE/'public'
WORK=HERE.parents[1]/'output'/'orb-product-demo'/'work'
BASE='https://jsnwiqkw5sqs3c7hag6ywd3ngm0vljpc.lambda-url.us-east-1.on.aws'
ORIGIN='https://orb-azure-ten.vercel.app'
result_path=PUBLIC/'live-result.json'
if result_path.exists():
    print('Existing sanitized live result reused; no additional request.',flush=True)
    raise SystemExit(0)
attempt_path=WORK/'live-attempt.json'
if attempt_path.exists():
    raise SystemExit('A prior attempt exists. Refusing automatic duplicate media submission.')
key=uuid.uuid4().hex
attempt_path.write_text(json.dumps({'idempotency_key':key,'state':'preparing'}),encoding='utf-8')
def safe(value):
    if isinstance(value,dict):
        return {k:safe(v) for k,v in value.items() if not any(p in k.lower() for p in ['token','wallet','signature','job_id'])
                and not k.lower().endswith('url') and k not in ['keys','artifacts_synced']}
    if isinstance(value,list):return [safe(v) for v in value]
    return value
try:
    response=requests.post(BASE+'/api/orb/judge-session',headers={'Origin':ORIGIN},json={'code':'OPENCV2026'},timeout=35)
    response.raise_for_status()
    token=response.json()['token']
    headers={'Origin':ORIGIN,'Authorization':'Bearer '+token,'X-Orb-Idempotency-Key':key}
    started=time.monotonic()
    with (PUBLIC/'original_reference.jpg').open('rb') as source:
        print('Submitting one original image Decode to AWS; no wallet transaction.',flush=True)
        response=requests.post(BASE+'/api/orb/decode/file?upload_attempt_id='+key,headers=headers,
                               files={'file':('shadowed_corridor.jpg',source,'image/jpeg')},timeout=145)
    response.raise_for_status()
    job=response.json()['job_id']
    attempt_path.write_text(json.dumps({'idempotency_key':key,'state':'submitted','job_id':job}),encoding='utf-8')
    deadline=time.monotonic()+150
    while True:
        status=requests.get(BASE+'/api/jobs/'+job,headers=headers,timeout=35)
        status.raise_for_status();payload=status.json()
        if payload['state']=='error':raise RuntimeError('Authorized demo job returned error')
        if payload['state']=='complete':break
        if time.monotonic()>deadline:raise TimeoutError('Status deadline exceeded; media POST not retried')
        time.sleep(1.5)
    response=requests.get(BASE+'/api/jobs/'+job+'/result',headers=headers,timeout=35)
    response.raise_for_status();result=response.json()
    cv=result['opencv_telemetry']
    for field,name in [('hud_preview_url','live_hud.jpg'),('clahe_preview_url','live_clahe.jpg')]:
        url=cv.get(field) or cv.get('aws_s3',{}).get('hud_s3_url' if field.startswith('hud') else 'clahe_s3_url')
        if not url:raise RuntimeError('Required live artifact unavailable')
        media=requests.get(url if url.startswith('https://') else BASE+url,
                           headers={} if url.startswith('https://') else headers,timeout=35)
        media.raise_for_status();(PUBLIC/name).write_bytes(media.content)
    clean=safe(result)
    clean['provider']='Orb AI'
    clean['demo_provenance']={'source':'Single authorized live AWS judge Decode of an original generated example image',
      'elapsed_seconds':round(time.monotonic()-started,2),'private_fields_removed':True}
    result_path.write_text(json.dumps(clean,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'state':'complete','runtime':cv.get('compute_badge'),'opencv':cv.get('opencv_version'),
      'processing_ms':cv.get('processing_ms'),'clahe':cv.get('clahe_applied'),'elapsed_seconds':clean['demo_provenance']['elapsed_seconds']}),flush=True)
except Exception as exc:
    print('Live sample did not complete: '+type(exc).__name__+'. No automatic media retry.',flush=True)
    raise SystemExit(1)

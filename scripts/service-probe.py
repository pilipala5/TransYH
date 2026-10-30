"""Probe a user-configured service. Credentials arrive on stdin, never argv."""
import json
import logging
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
import httpx
import openai
from api_client import api_mode, create_text

logging.disable(logging.CRITICAL)
cfg = json.loads(sys.stdin.readline())
try:
    if not cfg.get('apiKey'):
        from macos_keychain import get_api_key
        cfg['apiKey']=get_api_key(cfg['baseURL'])
    with openai.OpenAI(base_url=cfg['baseURL'], api_key=cfg['apiKey'], max_retries=0,
        http_client=httpx.Client(timeout=30, follow_redirects=False)) as client:
        if cfg.get('model'):
            kwargs={}
            prompt='Translate into Simplified Chinese. Output translation only: Scientific papers contain mathematical equations, images, and tables.'
            if cfg.get('requestMode')=='layout':
                kwargs={'max_tokens':2048,'extra_body':{}}
                prompt='Translate the input to Simplified Chinese. Return only a JSON array with the same id and an output field. Preserve all tags and placeholders. Input: [{"id":0,"input":"Scientific papers contain mathematical equations, images, and tables."}]'
            response=create_text(client,model=cfg['model'],mode=api_mode(cfg),messages=[{'role':'user','content':prompt}],**kwargs)
            print(json.dumps({'ok':True,'model':cfg['model'],'translation':response.text,
                'tokens':response.total_tokens},ensure_ascii=False))
        else:
            print(json.dumps({'ok':True,'models':[m.id for m in client.models.list()]},ensure_ascii=False))
except openai.APIStatusError as exc:
    body=exc.body if isinstance(exc.body,dict) else {}
    detail=body.get('error',body)
    message=str(detail.get('message','')) if isinstance(detail,dict) else ''
    categories={name:bool(re.search(pattern,message,re.I)) for name,pattern in {
        'no_accounts':'no.*available.*account|暂无.*账号|没有.*账号|无可用',
        'quota':'quota|额度|限额|余额',
        'cooldown':'cooldown|cooling|冷却',
        'client_block':'cloudflare|user.agent|1010|403|forbidden',
        'upstream':'upstream|上游',
        'model':'model|模型',
    }.items()}
    print(json.dumps({'ok':False,'status':exc.status_code,'code':detail.get('code') if isinstance(detail,dict) else None,
        'type':detail.get('type') if isinstance(detail,dict) else None,'categories':categories,'error':'API returned a non-success status'}))
except Exception as exc:
    print(json.dumps({'ok':False,'error':type(exc).__name__}))

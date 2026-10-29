"""Score exact spans against six user-confirmed synthetic reference labels.

Default: scripted loopback Mock, which measures engineering guards, NOT model
accuracy. --live explicitly reads the existing API configuration from stdin;
it sends only this synthetic sample and incurs provider requests. No secrets
or provider responses are written into the report.
"""
from pathlib import Path
import argparse
import json
import logging
import sqlite3
import sys
import threading
import uuid
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'engine'),str(ROOT/'tests')]
from highlight_fixtures import GOLD,create
from highlight_pdf import extract
import pymupdf
import worker
from mock_api import Handler


def evaluate(destination,live=False):
    logging.disable(logging.CRITICAL)
    worker.emit=lambda *args,**kwargs:None
    run=ROOT/'tests/output/highlight-evaluation'/str(uuid.uuid4())
    run.mkdir(parents=True,mode=0o700)
    source=create(run/'reference.pdf')
    server=None
    if live:
        config=json.loads(sys.stdin.readline())
    else:
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        config={'baseURL':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture-highlight-evaluation','apiKey':'fixture-only-key'}
    try:
        result=worker.highlight_action('highlight',{**config,'input':str(source),
            'outputDir':str(run/'output'),'cacheDir':str(run/'cache')})
    finally:
        if server:server.shutdown()
    with pymupdf.open(source) as pdf:paragraphs={p['paragraph_id']:p for p in extract(pdf)}
    with sqlite3.connect(run/'cache/highlight-cache.sqlite3') as db:
        records=[row for (value,) in db.execute('SELECT offsets FROM selections') for row in json.loads(value)]
    selected={(paragraphs[r['paragraph_id']]['text'][r['start']:r['end']],r['type']) for r in records}
    expected={(g['quote'],g['type']) for g in GOLD if g['type']}
    positives=selected&expected
    report={'schema':1,'reference':'tests/fixtures/highlight-gold.json',
        'referenceConfirmation':'Six synthetic labels explicitly approved by the user on 2026-10-29',
        'selector':'live API from stdin' if live else 'scripted Mock; candidates derive from reference fixture',
        'interpretation':'Exact reference-span scoring. Mock scores validate filtering/mapping only and are NOT semantic model accuracy or real-paper performance.',
        'referenceCases':len(GOLD),'positiveCases':len(expected),'negativeCases':sum(g['type'] is None for g in GOLD),
        'truePositive':len(positives),'falsePositive':len(selected-expected),'falseNegative':len(expected-selected),
        'requests':result['requests'],'highlightCount':result['highlightCount'],
        'cases':[{'id':g['id'],'expected':g['type'],'selected':(g['quote'],g['type']) in selected if g['type'] else any(g['quote'] in q for q,t in selected)} for g in GOLD]}
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--output',default=str(ROOT/'tests/output/highlight-evaluation.json'))
    arguments=parser.parse_args()
    try:evaluate(arguments.output,arguments.live)
    except worker.UserError as error:raise SystemExit(str(error)) from None
    except Exception:raise SystemExit('Highlight evaluation did not complete; no provider body or credentials printed.') from None

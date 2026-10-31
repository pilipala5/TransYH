"""Offline OpenAI-compatible fixture service. Never use as a real translator."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import re
import time
import threading


def fixture_translation(text):
    terms = {
        'Layout-Preserving Scientific Translation': '保留版式的科研论文翻译',
        'Mathematical Model and Visual Evidence': '数学模型与可视化证据',
        'Two-Column Results and Discussion': '双栏结果与讨论',
        'TransYH Development Team': 'TransYH 开发团队',
        'Synthetic Evaluation Paper': '合成评测论文',
        'Introduction': '引言', 'Experimental Setting': '实验设置',
        'Abstract.': '摘要。', 'Method': '方法', 'Precision': '精确率', 'Recall': '召回率',
        'Baseline': '基线方法', 'Proposed': '提出的方法',
        'Table 1. Illustrative measurements': '表 1. 示例测量结果',
        'Figure 1. A synthetic trend used only for image preservation testing.': '图 1. 仅用于测试图像保留的合成趋势。',
    }
    for en,zh in sorted(terms.items(), key=lambda x:-len(x[0])):
        text=text.replace(en,zh)
    chunks = re.split(r"(<[^>]*>|\{v\d+\})", text)
    for i,chunk in enumerate(chunks):
        if chunk.startswith('<') or re.fullmatch(r'\{v\d+\}',chunk): continue
        if re.search(r'[A-Za-z]{4}',chunk) and (len(chunk)>85 or not re.search(r'[\u4e00-\u9fff]',chunk)):
            # Deterministic fixture-only paragraph text with a comparable length;
            # this checks the engine/layout plumbing, never model quality.
            n=max(1,min(6,len(chunk)//85))
            chunks[i]='科研论文包含正文、数学公式、图像与表格。翻译时保留页面结构、阅读顺序和图像位置。' * n
    return ''.join(chunks)


class Handler(BaseHTTPRequestHandler):
    calls=0
    requests=[]
    metrics={}
    controls={}
    lock=threading.Lock()
    def log_message(self, *_): pass
    def do_GET(self):
        if self.path=='/stats':
            with Handler.lock:
                stats={'calls':Handler.calls,'models':{k:dict(v) for k,v in Handler.metrics.items()}}
            self.reply(200, stats)
        else:self.reply(404, {'error':{'message':'not found'}})
    def reply(self,status,data):
        encoded=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers()
        try:self.wfile.write(encoded)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
        model=data.get('model','')
        if self.path=='/control':
            with Handler.lock: Handler.controls[model]=data
            self.reply(200,{'ok':True});return
        with Handler.lock:
            Handler.calls+=1
            metrics=Handler.metrics.setdefault(model,{'active':0,'peakConcurrent':0,'calls':0})
            metrics['active']+=1;metrics['calls']+=1
            metrics['peakConcurrent']=max(metrics['peakConcurrent'],metrics['active'])
            call_number=metrics['calls']
            control=dict(Handler.controls.get(model,{}))
        try:
            if control.get('delay'):time.sleep(control['delay'])
            if control.get('failAfter') is not None and call_number>control['failAfter']:
                self.reply(401,{'error':{'message':'controlled-partial-failure'}});return
            self.handle_request(data,model)
        finally:
            with Handler.lock:metrics['active']-=1

    def handle_request(self,data,model):
        if model in ('error-401','error-403','error-404','error-429','error-500'):
            self.reply(int(model[-3:]),{'error':{'message':'provider-error-body-must-not-leak'}});return
        if model=='slow':time.sleep(2)
        if model.startswith('fixture-e2e-'):time.sleep(2)
        if model=='invalid':self.reply(200,{'unexpected':True});return
        if model=='empty':self.reply(200,{'choices':[{'message':{'content':''}}]});return
        if model=='redirect':
            self.send_response(307);self.send_header('Location','http://127.0.0.1:1/leak');self.end_headers();return
        if not self.path.endswith('/chat/completions'):self.reply(404,{});return
        text=data['messages'][-1]['content']
        if any('严谨的学术论文精读助手' in m.get('content','') for m in data['messages']):
            # Deliberately scripted candidates, not an AI accuracy evaluation.
            from highlight_fixtures import GOLD,DENSITY_CASES,RECALL_CASES
            payload=json.loads(text)
            highlights=[]
            control=Handler.controls.get(model,{})
            if control.get('requireContext'):
                context=payload.get('paper_context',{})
                if not context.get('title') or not context.get('abstract') or not context.get('sections'):
                    self.reply(400,{'error':{'message':'missing-paper-context'}});return
            if 'capture' in control:control['capture'].append(payload)
            reference=DENSITY_CASES if model.startswith('fixture-density-') else RECALL_CASES if model.startswith('fixture-recall-') else GOLD
            for paragraph in payload['paragraphs']:
                for gold in reference:
                    # These are scripted semantic decisions, including negative
                    # examples. Local regexes no longer make these judgments.
                    if gold['type'] and gold['quote'] in paragraph['text']:
                        highlights.append({'paragraph_id':paragraph['paragraph_id'],'quote':gold['quote'],
                            'type':gold['type'],
                            'confidence':.99,'importance':gold.get('importance','core')})
            if 'candidates' in control:highlights=control['candidates']
            output=json.dumps({'highlights':highlights},ensure_ascii=False)
            if model.startswith('fixture-highlight-invalid'):output='not valid JSON'
        elif '## Here is the input:' in text:
            rows=json.loads(text.split('## Here is the input:')[-1])
            output=json.dumps([{'id':row['id'],'output':fixture_translation(row['input'])} for row in rows],ensure_ascii=False)
        elif 'Input:\n\n' in text:output=fixture_translation(text.split('Input:\n\n')[-1])
        elif 'Now translate the following text:' in text:output=fixture_translation(text.split('Now translate the following text:')[-1].strip())
        else:output='OK'
        self.reply(200,{'id':'mock-fixture','object':'chat.completion','created':1,'model':model,
            'choices':[{'index':0,'message':{'role':'assistant','content':output},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18761);args=p.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Mock API listening on 127.0.0.1:{server.server_port}',flush=True)
    server.serve_forever()

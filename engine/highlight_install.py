"""Backup-first, atomic PDF installation and crash recovery. No network calls.

Prepared (unconfirmed) writes roll back on recovery. Committed writes retain the
new PDF and the original backup. Unknown external edits are never overwritten.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid

from highlight_pdf import HighlightError, fingerprint, verify_preserved


def sync_directory(path):
    if os.name == 'nt':return # Directory fsync is not available through os.open on Windows.
    descriptor=os.open(path,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def atomic_json(path,value):
    temporary=path.with_name(path.name+'.tmp')
    with os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),'w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path);sync_directory(path.parent)


def durable_copy(source,target):
    with Path(source).open('rb') as original,os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as copy:
        for chunk in iter(lambda:original.read(1024*1024),b''):copy.write(chunk)
        copy.flush();os.fsync(copy.fileno())
    sync_directory(Path(target).parent)


def recover_one(journal):
    row=json.loads(journal.read_text(encoding='utf-8'))
    target,backup,temporary=map(Path,[row['target'],row['backup'],row['temporary']])
    if row['status'] in ('committed','rolled_back'):return 'unchanged'
    if row['status']!='prepared' or fingerprint(backup)!=row['before']:
        raise HighlightError('标注备份或恢复记录异常，未覆盖 PDF，请检查本地备份。')
    current=fingerprint(target) if target.is_file() else None
    if current not in (row['before'],row['after'],None):
        raise HighlightError('中文 PDF 在中断后被其他程序修改，未覆盖；原备份保留。')
    if current!=row['before']:
        restoration=target.with_name('.transyh-restore-'+str(uuid.uuid4())+'.pdf')
        durable_copy(backup,restoration);os.replace(restoration,target);sync_directory(target.parent)
    temporary.unlink(missing_ok=True)
    row['status']='rolled_back';atomic_json(journal,row)
    return 'rolled_back'


def recover(directory):
    directory=Path(directory)
    recovered=0
    if directory.exists():
        for journal in sorted((directory/'transactions').glob('*.json')):
            if recover_one(journal)=='rolled_back':recovered+=1
    return {'recoveredTransactions':recovered}


def install(config):
    if config.get('protectedOriginal') and os.path.samefile(config['input'],config['protectedOriginal']):
        raise HighlightError('中文附件指向英文原件，未写入标注。')
    recover(config['installDir'])
    target=Path(config['input']).resolve()
    candidate=Path(config['candidatePath']).resolve()
    if target==candidate or fingerprint(target)!=config['sourceFingerprint']:
        raise HighlightError('中文 PDF 已变化，未写入标注，请重试。')
    verify_preserved(target,candidate)
    directory=Path(config['installDir'])
    for name in ('transactions','backups'):(directory/name).mkdir(parents=True,exist_ok=True,mode=0o700)
    token=str(uuid.uuid4())
    backup=directory/'backups'/(token+'.pdf')
    temporary=target.with_name('.transyh-'+token+'.pdf')
    journal=directory/'transactions'/(token+'.json')
    before=config['sourceFingerprint'];after=fingerprint(candidate)
    durable_copy(target,backup)
    if fingerprint(backup)!=before or fingerprint(target)!=before:
        raise HighlightError('备份期间中文 PDF 已变化，未覆盖；备份保留。')
    row={'schema':1,'status':'prepared','target':str(target),'backup':str(backup),'temporary':str(temporary),'before':before,'after':after}
    atomic_json(journal,row)
    try:
        durable_copy(candidate,temporary)
        if fingerprint(target)!=before:raise HighlightError('中文 PDF 已被其他程序修改，未覆盖。')
        os.replace(temporary,target);sync_directory(target.parent)
        if fingerprint(target)!=after:raise HighlightError('标注写入核验失败。')
        row['status']='committed';atomic_json(journal,row)
    except Exception:
        recover_one(journal)
        raise HighlightError('标注保存未完成，已保留原译文和备份。') from None
    return {'installed':True,'backupPath':str(backup)}

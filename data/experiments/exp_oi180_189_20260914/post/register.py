"""Register verified signal-tranche BASE summaries, preserving previous ledger rows."""
import csv
import hashlib
import json
import os
import sys
import subprocess
import io
from pathlib import Path
EXP=Path(__file__).resolve().parents[1]
ROOT=EXP.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw
import clean_derived_artifacts as ledger


def read(path):
    with path.open() as f:return list(csv.DictReader(f))


def main():
    v=json.loads((EXP/'verification.json').read_text())
    assert v['complete_pairing'] and v['zero_negative_cash']
    assert next(r for r in v['guardrails'] if r['group']=='full' and r['bp']==0)['track_a_pass']
    # §12 第7款：成本压力必须报告，档位不作否决线。
    assert v['current_baseline_winners_unchanged'], '须另外补齐新 BASE 前五赢家剔除集'
    winners=json.loads((EXP/'winners.json').read_text())['by_arm']['SIGNAL']
    rows=[r for r in read(EXP/'summary_rows.csv') if r['arm']=='SIGNAL' and r['group'] in ('full','A') and r['bp']=='0']
    assert len(rows)==28
    key=lambda r:(r['扫描标签'],r['策略'],r['计量版本'])
    before={key(r):r for r in read(ledger.MERGED)}
    committed_csv=subprocess.check_output(['git','show','HEAD:data/backtest/scan_summaries.csv'],cwd=ROOT,text=True)
    committed={key(r):r for r in csv.DictReader(io.StringIO(committed_csv))}
    paths=[];published=[]
    for r in rows:
        tag=sw.summary_tag('BASE',r['start'],','.join(winners) if r['group']=='A' else '')
        clean={k:x for k,x in r.items() if k not in ('group','arm','start','bp','tag')}
        suffix='_'+r['tag']; assert clean['策略'].endswith(suffix) and '_lrc3_' in clean['策略']
        clean['策略']=clean['策略'][:-len(suffix)]+'_'+tag
        target=sw.OUT_DIR/f'summary_{tag}.csv'
        old=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        tmp=target.with_name('.'+target.name+'.oi180_189')
        with tmp.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(clean));w.writeheader();w.writerow(clean)
        tmp.replace(target);paths.append(target)
        published.append(dict(path=str(target.relative_to(ROOT)),before_sha256=old,after_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    names={p.name for p in paths}
    with os.scandir(sw.OUT_DIR) as it:entries=[e for e in it if e.name in names]
    ledger.write_ledger(entries)
    after={key(r):r for r in read(ledger.MERGED)}
    assert before.keys()<=after.keys(), '旧键不得删除'
    assert committed.keys()<=after.keys() and all(after[k]==r for k,r in committed.items()), '本批之前的已登记行不得改写'
    assert len(after)-len(before) in (0,28)
    (EXP/'registration.json').write_text(json.dumps(dict(registered_base_rows=28,old_rows_preserved=True,
        new_keys=len(after)-len(before),batch_new_keys=len(after)-len(committed),final_job='26683497',strategy_marker='sig1_lrc3',entry_point='clean_derived_artifacts.write_ledger',published=published),indent=2)+'\n')
    print('REGISTERED 28 signal-tranche BASE summaries; old rows preserved.')


if __name__=='__main__':main()

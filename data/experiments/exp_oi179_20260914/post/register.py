"""Publish verified ca2 BASE summaries and retain prior ledger keys."""
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare import EXP,ROOT,save,sw
import clean_derived_artifacts as ledger
sys.path.insert(0,str(ROOT/'scripts/experimental'))
from ex_winner_symmetry import top5


def read(p):
    with p.open(newline='') as f:return list(csv.DictReader(f))


def main():
    v=json.loads((EXP/'verification.json').read_text())
    av=json.loads((EXP/'analysis_verification.json').read_text())
    extra=json.loads((EXP/'extra_verification.json').read_text())
    assert v['track_a_pass'] and v['inputs_unchanged'] and v['baseline_values_checked']==1316
    assert av['complete_start_and_window_sets'] and av['negative_cash_days']==0
    assert extra['signal_count_and_median_checks']==96
    rows=[r for r in read(EXP/'summary_rows.csv') if r['group'] in ('full','A')]
    assert len(rows)==168
    key=lambda r:(r['扫描标签'],r['策略'],r['计量版本'])
    before={key(r):r for r in read(ledger.MERGED)}
    out=EXP/'cache/register';out.mkdir(exist_ok=True)
    paths=[];published=[]
    for r in rows:
        base=r['arm']=='BASE'
        excluded=','.join(v['current_winners']) if r['group']=='A' else ''
        tag=sw.summary_tag('BASE',r['start'],excluded) if base else f"OI17920260914_MS{r['arm']}{r['start'].replace('-','')}{'ex5' if excluded else ''}"
        target=sw.OUT_DIR/f'summary_{tag}.csv' if base else out/f'summary_{tag}.csv'
        clean={k:x for k,x in r.items() if k not in ('group','arm','start','nav_tag')}
        assert '_ca2_' in clean['策略']
        if base:
            suffix='_'+r['nav_tag'];assert clean['策略'].endswith(suffix),clean['策略']
            clean['策略']=clean['策略'][:-len(suffix)]+'_'+tag
        old_sha=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        tmp=target.with_name('.'+target.name+f'.oi179.{os.getpid()}')
        with tmp.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(clean),lineterminator='\n');w.writeheader();w.writerow(clean)
        os.replace(tmp,target);paths.append(target)
        if base:published.append(dict(path=str(target.relative_to(ROOT)),before_sha256=old_sha,
                                     after_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    entries=[]
    for parent in {p.parent for p in paths}:
        names={p.name for p in paths if p.parent==parent}
        with os.scandir(parent) as iterator:entries.extend(e for e in iterator if e.name in names)
    update=ledger.write_ledger(entries)
    after={key(r):r for r in read(ledger.MERGED)}
    assert before.keys()<=after.keys() and all(after[k]==r for k,r in before.items()),'Old rows changed'
    assert len(after)-len(before)==168,(len(before),len(after))
    assert sorted(top5('BASE',sw.EX5_ANCHOR_START))==v['current_winners']
    save('registration.json',dict(registered_base_rows=28,registered_candidate_rows=140,
        old_rows_preserved=True,ledger_before=len(before),ledger_after=len(after),new_keys=168,
        published=published,entry_point='clean_derived_artifacts.write_ledger',strategy_marker='ca2',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    print('REGISTERED: 28 current BASE summaries and 140 candidate summaries; old ledger rows preserved.',flush=True)


if __name__=='__main__':main()

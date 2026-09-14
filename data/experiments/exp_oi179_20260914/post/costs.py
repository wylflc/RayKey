"""Fixed 0/10/20/30 bp execution-cost disclosure for the track-A correction."""
import csv
import json
import os
import shlex
import statistics as st
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare import EXP,ROOT,save,sw,fingerprint
from run import numeric,write_rows


def main():
    m=json.loads((EXP/'manifest.json').read_text());v=json.loads((EXP/'guardrail.json').read_text())
    assert fingerprint({ROOT/p for p in m['inputs']})==m['inputs']
    workers=min(48,int(os.environ['SLURM_CPUS_PER_TASK']));a=v['old_winners'];refs=m['frozen_reference_inputs']
    cache=EXP/'cache/costs';cache.mkdir(exist_ok=True)
    def one(job):
        bp,group,arm,start=job;tag=f'{arm}COST{bp}{group}{start.replace("-","")}'
        cmd=[sys.executable,str(EXP/'engine.py'),*shlex.split(m['base']),*m['state_args'],
             '--slope-arm',arm,'--since',start,'--label-suffix','_'+tag,'--out-dir',str(cache),
             '--slippage-bp',str(bp),'--equity-bond-data',refs['data/reference/equity_bond_csi300.csv']]
        if group=='A':cmd+=['--exclude-codes',','.join(a)]
        env=dict(os.environ,RAYKEY_ACTIONS=str(ROOT/refs['data/raw/corporate_actions/a_share_corporate_actions.csv']),
                 RAYKEY_RATES=str(ROOT/refs['data/reference/cost_of_equity_inputs.csv']))
        if '--reuse-completed' not in sys.argv or not (cache/f'summary_{tag}.csv').exists():
            with (EXP/'errors'/f'{tag}.txt').open('w') as err:
                subprocess.run(cmd,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=err,env=env,check=True)
        r=next(csv.DictReader((cache/f'summary_{tag}.csv').open()));assert r['负现金日数']=='0'
        return dict(bp=bp,group=group,arm=arm,start=start,nav_tag=tag,**r)
    jobs=[(bp,g,arm,s) for bp in (10,20,30) for g in ('full','A') for arm in ('LEGACY','BASE') for s in sw.DEFAULT_STARTS]
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in as_completed([pool.submit(one,j) for j in jobs]):
            rows.append(f.result())
            if len(rows)%28==0:print(f'COST {len(rows)}/{len(jobs)}',flush=True)
    for r in csv.DictReader((EXP/'guard_summary_rows.csv').open()):
        if r['group'] in ('guardfull','guardA'):rows.append(dict(r,bp=0,group='full' if r['group']=='guardfull' else 'A'))
    rows.sort(key=lambda r:(r['bp'],r['group'],r['arm'],r['start']))
    write_rows('cost_summary_rows.csv',rows)
    paired=[]
    for bp in (0,10,20,30):
        for group in ('full','A'):
            arms={arm:{r['start']:numeric(r) for r in rows if r['bp']==bp and r['group']==group and r['arm']==arm} for arm in ('LEGACY','BASE')}
            assert not sw.pairing_defects(arms,'BASE','LEGACY',sw.DEFAULT_STARTS,group)
            for comparison in ('FIX_vs_LEGACY','LEGACY_vs_0'):
                cand=arms['BASE'] if comparison=='FIX_vs_LEGACY' else arms['LEGACY']
                base=arms['LEGACY'] if comparison=='FIX_vs_LEGACY' else {r['start']:numeric(r) for r in rows if r['bp']==0 and r['group']==group and r['arm']=='LEGACY'}
                values={k:st.median(sw.start_delta(cand[s],base[s],k) for s in sw.DEFAULT_STARTS) for k in ('年化',sw.WIN5_KEY,'滚动5年回撤中位','最低担保比例','强平次数')}
                flips=sum(sw.neg_window_flip(cand[s],base[s]) for s in sw.DEFAULT_STARTS)
                passed=values['年化']>=-.01 and values[sw.WIN5_KEY]>=-.01 and values['滚动5年回撤中位']<=.03 and flips<=7
                paired.append(dict(bp=bp,group=group,comparison=comparison,cagr_delta_pp=values['年化']*100,
                    P_delta_pp=values[sw.WIN5_KEY]*100,roll5dd_delta_pp=values['滚动5年回撤中位']*100,
                    margin_delta_pp=values['最低担保比例']*100,forced_delta=values['强平次数'],negative_flips=flips,
                    track_a_reading=passed))
    write_rows('cost_paired.csv',paired)
    assert fingerprint({ROOT/p for p in m['inputs']})==m['inputs']
    save('cost_verification.json',dict(executed_paths=len(jobs),reused_zero_paths=56,rows=len(rows),inputs_unchanged=True,
        candidates=1,slippage_bp=[0,10,20,30],job_id=os.getenv('SLURM_JOB_ID')))
    print('COST PRESSURE COMPLETE',flush=True)


if __name__=='__main__':main()

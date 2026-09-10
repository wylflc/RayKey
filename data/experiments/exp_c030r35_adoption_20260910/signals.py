"""Run unchanged standard diagnostics and capture their daily observations."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import contextlib
import inspect
import json
import shlex
import statistics as st
import subprocess
import sys
from common import EXP, ROOT, load_module, save, fingerprint

SCRIPTS=ROOT/'scripts/experimental'
sys.path.insert(0,str(SCRIPTS))


def instrument(module,capture):
    source=inspect.getsource(module.main)
    assert source.count('    return 0')==1
    module.__dict__['_capture_result']=capture
    exec(compile(source.replace('    return 0','    _capture_result(locals())\n    return 0'),
                 str(module.__file__),'exec'),module.__dict__)


def selection_capture(module,v,path):
    rank_groups={label:defaultdict(lambda:([],[])) for label in ('1_vs_2_5','1_vs_6_10')}
    for (day,code),(rank,pv,held) in v['cand'].items():
        if code not in v['rets']:continue
        fr=module.forward_return(*v['rets'][code],day,v['args'].horizon)
        if fr is None:continue
        for label,(lo,hi) in {'1_vs_2_5':(2,5),'1_vs_6_10':(6,10)}.items():
            if rank==1:rank_groups[label][day][0].append(fr)
            elif lo<=rank<=hi:rank_groups[label][day][1].append(fr)
    obj=dict(selection=v['res1'],swap=v['res3'],independent_pairs=len(v['swap_pairs']),
             ranks_daily={k:module.daily_paired(g) for k,g in rank_groups.items()},
             ranks_pooled={str(k):dict(n=len(g),median=st.median(g),mean=st.fmean(g))
                           for k,g in v['g_rank'].items() if g})
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def swap_capture(v,path):
    daily={d:dict(actual=st.median(v['d_act'][d]),buy=st.median(v['d_buy'][d]),
                  sell=st.median(v['d_sell'][d]),
                  excess=st.median(v['d_buy'][d])-st.median(v['d_sell'][d])) for d in sorted(v['d_act'])}
    obj=dict(daily=daily,per_year=v['per_year'],synthetic=v['syn'],panel_rho=v['rho_y'],
             panel_spread=v['sp_y'],used=v['used'],skipped=v['skipped'],
             independent_pairs=len({(s,t) for _,s,t in v['swaps']}),
             yearly_pairs={y:len({(s,t) for d,s,t in v['swaps'] if d[:4]==y})
                           for y in sorted({d[:4] for d,_,_ in v['swaps']})})
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def worker(mode,arm,value):
    manifest=json.loads((EXP/'manifest.json').read_text())
    states=manifest['state_args']
    base=shlex.split(manifest['base'])
    panel=base[base.index('--universe-file')+1]
    candidate_states=states[states.index('--daily-states')+1]
    hold_states=states[states.index('--hold-states')+1]
    out=EXP/'sig'/arm
    argv=['diagnostic','--candidate-log',str(out/'candidates.csv'),'--trade-log',str(out/'ledger.csv')]
    if mode=='selection':
        stem=f'selection_{value}d'
        module=load_module('standard_selection',SCRIPTS/'selection_edge_audit.py')
        instrument(module,lambda v:selection_capture(module,v,out/f'{stem}.json'))
        argv+=['--horizon',value]
    elif mode=='swap':
        stem=f'swap_tol{value}'
        module=load_module('standard_swap',SCRIPTS/'swap_regime_control.py')
        instrument(module,lambda v:swap_capture(v,out/f'{stem}.json'))
        argv+=['--states',candidate_states,'--hold-states',hold_states,'--panel',panel,
               '--horizon','250','--split','2017','--tol',value,'--since','2011-11-01']
    elif mode=='panel':
        out=EXP/'sig';stem='panel_tier_shared'
        module=load_module('standard_panel',SCRIPTS/'panel_tier_forward.py')
        argv=['diagnostic','--states',candidate_states,'--panel',panel,
              '--since','2005-01-01','--per-code-out',str(out/'panel_tier_per_code.csv')]
    else:
        raise ValueError(mode)
    sys.argv=argv
    with (out/f'{stem}.txt').open('w') as f,contextlib.redirect_stdout(f):
        assert module.main()==0


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--all',action='store_true')
    p.add_argument('--mode');p.add_argument('--arm',default='BASE');p.add_argument('--value',default='')
    args=p.parse_args()
    if not args.all:
        worker(args.mode,args.arm,args.value)
        return
    tasks=[('selection',a,str(h)) for a in ('BASE','C030R35') for h in (250,750)]
    tasks+=[('swap',a,f'{tol:.2f}') for a in ('BASE','C030R35') for tol in (.04,.10,.15)]
    tasks+=[('panel','BASE','')]
    def launch(t):
        subprocess.run([sys.executable,__file__,'--mode',t[0],'--arm',t[1],'--value',t[2]],
                       cwd=ROOT,check=True)
        print('SIGNAL COMPLETE',t,flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(launch,tasks))
    paths={a:next((EXP/'sig'/a).glob('*_trades.csv')) for a in ('BASE','C030R35')}
    with (EXP/'sig/delta_attribution.txt').open('w') as f:
        subprocess.run([sys.executable,str(SCRIPTS/'delta_attribution.py'),'--base',str(paths['BASE']),
                        '--arm',str(paths['C030R35'])],cwd=ROOT,stdout=f,check=True)
    from delta_attribution import load_contrib
    b,b_ok=load_contrib(paths['BASE']);c,c_ok=load_contrib(paths['C030R35'])
    assert b_ok and c_ok
    delta={k:c.get(k,0)-b.get(k,0) for k in set(b)|set(c)}
    ranked=sorted(((k,v) for k,v in delta.items() if abs(v)>1e-6),key=lambda kv:-abs(kv[1]))
    total=sum(v for _,v in ranked)
    save('attribution.json',dict(total=total,top3_net_share=sum(v for _,v in ranked[:3])/total,
         top3_gross_share=sum(abs(v) for _,v in ranked[:3])/sum(abs(v) for _,v in ranked),
         ranked=[dict(code=k,delta=v) for k,v in ranked]))
    # Panel diagnostics have identical panel, states, dates and price inputs in both arms.
    # Macro exposure does not enter this script; run once and explicitly reuse the result.
    outputs=set((EXP/'sig').glob('**/*.txt'))|set((EXP/'sig').glob('**/*.json'))
    save('signal_verification.json',dict(tasks_completed=tasks,attribution_complete=True,
         panel_shared_reason='Identical panel/state/price/forward-return inputs; exposure not used',
         panel_tiers_hindsight_2026=True,outputs=fingerprint(outputs)))


if __name__=='__main__':
    main()

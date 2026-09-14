"""Frozen old rank1 filtering versus current strategy's reranked rank1 signals."""
import argparse
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from prepare import EXP,ROOT,save
sys.path.insert(0,str(ROOT/'scripts/experimental'))
from pv_episode_forward import episodes,nonoverlap,write_csv
from moat_param_lab import total_return_index
import build_historical_valuation_bands as bhv
import backtest_valuation_strategy as bt
from slope import SlopeGuard


def summarize(key,events,rets,days,rows,counts,obs,details):
    cohort,arm,method,horizon=key
    for event in events:
        i=event['signal_i'];r=rows[days[i]];ed=r['exec_date']
        # Price index is supplied with the return dictionary, avoiding a calendar rebuild per event.
        tr,di=rets;start=di.get(ed);end=start+horizon if start is not None else None
        good=end is not None and end<len(days)
        ret=tr[days[end]]/tr[ed]-1 if good else None
        counts[key]+=1
        if good:obs[key].append((r['security_code'],days[i][:4],ret))
        if arm in ('BASE','BOTH1'):
            b=event.get('break_i')
            details.append(dict(cohort=cohort,arm=arm,method=method,horizon=horizon,code=r['security_code'],
                                signal_date=days[i],exec_date=ed,end_date=days[end] if good else '',
                                break_date=days[b] if b is not None else '',pv=r['pv'],
                                forward_return=ret,complete=good))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['old','current'],required=True);a=ap.parse_args()
    manifest=json.loads((EXP/'manifest.json').read_text())
    bt.ACTIONS=bhv.ACTIONS=ROOT/manifest['frozen_reference_inputs']['data/raw/corporate_actions/a_share_corporate_actions.csv']
    actions=bt.load_actions();legacy=bhv.load_actions();grid=json.loads((EXP/'grid.json').read_text())
    inputs={}
    if a.stage=='old':
        p=ROOT/'data/experiments/exp_selection_edge/candidates.csv'
        for spec in grid:inputs[spec['arm']]=(p,spec)
    else:
        for arm in ('BASE','BOTH1'):
            inputs[arm]=(EXP/'signals'/arm/'2011-11-01/candidates.csv',grid[0])
    logs={arm:defaultdict(dict) for arm in inputs}
    for arm,(p,spec) in inputs.items():
        for r in csv.DictReader(p.open()):
            if int(r['rank'])==1:
                c,d=r['security_code'],r['signal_date']
                assert d not in logs[arm][c]
                logs[arm][c][d]=r
    codes=set().union(*(set(d) for d in logs.values()))
    counts=defaultdict(int);obs=defaultdict(list);details=[];failures=[];gate_counts=defaultdict(lambda:dict(before=0,after=0))
    cohort='old_rank1_filter' if a.stage=='old' else 'current_rank1_rerank'
    for c in sorted(codes):
        raw=bhv.load_ohlcv(c);days=[d for d,p in raw];prices=[p for d,p in raw];di={d:i for i,d in enumerate(days)}
        ma=bt.adjusted_moving_averages(dict(raw),actions.get(c,{}),windows=(20,60));m60=[ma.get(d,{}).get(60) for d in days]
        tr=total_return_index(raw,legacy.get(c,[]));event_days=sorted(actions.get(c,{}));cursor=0;steps=[[] for _ in days]
        for i,d in enumerate(days):
            while cursor<len(event_days) and event_days[cursor]<=d:
                steps[i].append(actions[c][event_days[cursor]]);cursor+=1
        for arm,(_,spec) in inputs.items():
            rows=logs[arm].get(c,{})
            if not rows:continue
            assert set(rows)<=set(days)
            guard=SlopeGuard({c:dict(raw)},{c:ma},{c:actions.get(c,{})},spec)
            eligible=[d in rows and guard.allows(c,d) for d in days]
            gate_counts[arm]['before']+=len(rows);gate_counts[arm]['after']+=sum(eligible)
            if a.stage=='current' and arm=='BOTH1':
                check=SlopeGuard({c:dict(raw)},{c:ma},{c:actions.get(c,{})},grid[1])
                failures += [(c,d) for d in rows if not check.allows(c,d)]
            ep=episodes(eligible,prices,m60,steps);sp=episodes(eligible,prices,m60,steps,'stop')
            for h in (250,750):
                picks={'daily':[{'signal_i':i} for i,v in enumerate(eligible) if v],
                       'ma60_episode':ep,'ma60_nonoverlap':nonoverlap(ep,h),'stop_episode':sp}
                for method,events in picks.items():
                    summarize((cohort,arm,method,h),events,(tr,di),days,rows,counts,obs,details)
    summary=[];annual=[];company=[]
    for key,n in sorted(counts.items()):
        cohort,arm,method,h=key;xs=obs[key];cs=defaultdict(list);ys=defaultdict(list)
        for c,y,r in xs:cs[c].append(r);ys[y].append(r)
        vals=[r for c,y,r in xs]
        summary.append(dict(cohort=cohort,arm=arm,method=method,horizon=h,signals=n,complete=len(xs),codes=len(cs),missing=n-len(xs),
                            median=st.median(vals) if vals else None,mean=st.mean(vals) if vals else None,
                            positive_fraction=st.mean(r>0 for r in vals) if vals else None,
                            median_of_code_medians=st.median([st.median(v) for v in cs.values()]) if vals else None))
        annual += [dict(cohort=cohort,arm=arm,method=method,horizon=h,year=y,n=len(v),median=st.median(v)) for y,v in sorted(ys.items())]
        company += [dict(cohort=cohort,arm=arm,method=method,horizon=h,code=c,n=len(v),median=st.median(v)) for c,v in sorted(cs.items())]
    for name,rs in [('summary',summary),('annual',annual),('by_code',company),('observations',details)]:
        write_csv(EXP/f'signal_{a.stage}_{name}.csv',rs)
    reproduction={}
    if a.stage=='old':
        previous=list(csv.DictReader((ROOT/'data/experiments/exp_pv_episode_20260914/rank1_summary.csv').open()))
        for row in summary:
            if row['arm']!='BASE':continue
            old=next(r for r in previous if r['group']=='rank1_'+row['method'] and int(r['horizon'])==row['horizon'])
            assert row['complete']==int(old['complete']) and abs(row['median']-float(old['median']))<1e-12
            reproduction[f"{row['method']}_{row['horizon']}"]=True
    assert not failures,failures
    save(f'signal_{a.stage}_verification.json',dict(original_reproduction=reproduction,slope_failures=failures,gate_counts=gate_counts,
         stage=a.stage,return_basis='legacy dividends reinvested, fixed trading-day horizon; same as previous rank1 table',
         missing_exec_note='原exec_date无报价仍记缺失；周期锚可在下一有报价日建立，仅辅助，不冒充成交'))
    print(f'SIGNAL {a.stage} COMPLETE; gates {dict(gate_counts)}',flush=True)


if __name__=='__main__':main()

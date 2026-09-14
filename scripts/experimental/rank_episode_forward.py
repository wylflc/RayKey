#!/usr/bin/env python3
"""Re-evaluate a frozen rank-1 cohort with current event handling and MA60 cycles."""
from __future__ import annotations
import argparse
import bisect
import csv
import json
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pv_episode_forward import ROOT, bt, bhv, episodes, nonoverlap, return_indices, sha, write_csv
from moat_param_lab import total_return_index


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--candidate-log',type=Path,default=ROOT/'data/experiments/exp_selection_edge/candidates.csv')
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--require-original-table',action='store_true',
                    help='Historical-checkout audit only: fail unless the original table and trend membership reproduce.')
    args=ap.parse_args()
    rows=[r for r in csv.DictReader(args.candidate_log.open()) if int(r['rank'])==1]
    bycode=defaultdict(dict)
    for r in rows:
        c,d=r['security_code'],r['signal_date']
        if d in bycode[c]:raise ValueError(f'Duplicate rank1 {c} {d}')
        bycode[c][d]=r
    actions=bt.load_actions(); index_actions=bhv.load_actions()
    files=[args.candidate_log,bhv.ACTIONS,Path(__file__),Path(__file__).with_name('pv_episode_forward.py'),
           Path(__file__).with_name('moat_param_lab.py'),ROOT/'scripts/backtest_valuation_strategy.py',
           ROOT/'scripts/build_historical_valuation_bands.py',args.out/'rank1_preregister.md']
    hashes={str(p):sha(p) for p in files}
    obs=defaultdict(list); count=defaultdict(int)
    details=[]; missing_exec=[]; trend_mismatch=[]; anchor_delay=[]
    for c in sorted(bycode):
        raw=bhv.load_ohlcv(c); days=[d for d,p in raw]; prices=[p for d,p in raw]
        hashes[str(bhv.OHLCV_DIR/f'{c}.csv')]=sha(bhv.OHLCV_DIR/f'{c}.csv')
        di={d:i for i,d in enumerate(days)}
        reinvested=total_return_index(raw,index_actions.get(c,[]))
        tri,_,_=return_indices(days,prices,actions.get(c,{}))
        ma=bt.adjusted_moving_averages(dict(raw),actions.get(c,{}),windows=(20,60))
        eligible=[d in bycode[c] for d in days]
        if sum(eligible)!=len(bycode[c]):raise ValueError('Missing signal-date price')
        m60=[ma.get(d,{}).get(60) for d in days]
        events=sorted(actions.get(c,{})); cursor=0; steps=[[] for _ in days]
        for i,d in enumerate(days):
            while cursor<len(events) and events[cursor]<=d:
                steps[i].append(actions[c][events[cursor]]);cursor+=1
            if eligible[i] and not (prices[i]>ma.get(d,{}).get(20,float('inf'))>ma.get(d,{}).get(60,float('inf'))):
                trend_mismatch.append({'code':c,'signal_date':d})
        ep=episodes(eligible,prices,m60,steps)
        sp=episodes(eligible,prices,m60,steps,'stop')
        for e in sp:
            r=bycode[c][days[e['signal_i']]]
            if r['exec_date'] not in di:anchor_delay.append(r)
        for h in (250,750):
            picks={'rank1_daily':[{'signal_i':i,'break_i':None} for i,v in enumerate(eligible) if v],
                   'rank1_ma60_episode':ep,'rank1_stop_episode':sp,
                   'rank1_ma60_nonoverlap':nonoverlap(ep,h)}
            for g,es in picks.items():
                for e in es:
                    sd=days[e['signal_i']];r=bycode[c][sd];ed=r['exec_date'];start=di.get(ed)
                    end=start+h if start is not None else None
                    good=end is not None and end<len(days)
                    ret=reinvested[days[end]]/reinvested[ed]-1 if good else None
                    correct=tri[end]/tri[start]-1 if good else None
                    count[g,h]+=1
                    if good:obs[g,h].append((c,sd[:4],ret,correct))
                    if start is None and g=='rank1_daily' and h==250:missing_exec.append(r)
                    b=e.get('break_i')
                    details.append({'group':g,'horizon':h,'code':c,'signal_date':sd,'exec_date':ed,
                                    'pv':r['pv'],'held':r['held'],'break_date':days[b] if b is not None else '',
                                    'end_date':days[end] if good else '',
                                    'calendar_days':(date.fromisoformat(days[end])-date.fromisoformat(ed)).days if good else None,
                                    'return':ret,'corrected_return':correct,'complete':good,
                                    'missing_reason':'' if good else 'execution_quote_missing' if start is None else 'forward_incomplete'})
    summary=[]; annual=[]; company=[]
    for (g,h),n in sorted(count.items()):
        xs=obs[g,h];cs=defaultdict(list);ys=defaultdict(list)
        for c,y,r,q in xs:cs[c].append(r);ys[y].append(r)
        vals=[r for c,y,r,q in xs]; corrected=[q for c,y,r,q in xs]
        summary.append({'group':g,'horizon':h,'signals':n,'complete':len(xs),'codes':len(cs),'missing':n-len(xs),
                        'median':st.median(vals),'mean':st.mean(vals),'positive_fraction':st.mean(r>0 for r in vals),
                        'median_of_code_medians':st.median([st.median(v) for v in cs.values()]),
                        'corrected_median':st.median(corrected),
                        'max_code_sample_fraction':max(map(len,cs.values()))/len(xs)})
        annual += [{'group':g,'horizon':h,'year':y,'n':len(v),'median':st.median(v)} for y,v in sorted(ys.items())]
        company += [{'group':g,'horizon':h,'code':c,'n':len(v),'median':st.median(v)} for c,v in sorted(cs.items())]
    expected={250:(2833,28.08),750:(2322,94.44)}
    checks={}
    for r in summary:
        if r['group']=='rank1_daily':
            n,m=expected[r['horizon']]
            checks[str(r['horizon'])]=r['complete']==n and round(r['median']*100,2)==m
    write_csv(args.out/'rank1_summary.csv',summary)
    write_csv(args.out/'rank1_observations.csv',details)
    write_csv(args.out/'rank1_annual.csv',annual)
    write_csv(args.out/'rank1_by_code.csv',company)
    result={'completed_at_utc':datetime.now(timezone.utc).isoformat(),'job_id':os.getenv('SLURM_JOB_ID'),
            'original_table_reproduced':checks,'rank1_signals':len(rows),'trend_mismatches':trend_mismatch,
            'return_basis':'complete-event-calendar self-financing reinvestment (OI-179)',
            'cohort_note':'Frozen historical rank1; current trend mismatches are disclosed, not silently removed.',
            'missing_exec_quotes':missing_exec,'stop_anchor_delayed_signals':anchor_delay,
            'input_sha256':hashes,'results':summary,
            'output_sha256':{p.name:sha(p) for p in args.out.glob('rank1_*.csv')}}
    (args.out/'rank1_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'reproduction':checks,'trend_mismatch_n':len(trend_mismatch),'results':summary},ensure_ascii=False,indent=2))
    if args.require_original_table and (not all(checks.values()) or trend_mismatch):
        raise SystemExit('Frozen rank1 validation failed; inspect manifest before interpreting.')


if __name__=='__main__':main()

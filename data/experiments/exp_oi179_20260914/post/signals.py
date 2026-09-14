"""Separate return/calendar corrections, frozen selection, and current reranking."""
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare import EXP,ROOT,save
sys.path.insert(0,str(ROOT/'scripts/experimental'))
from pv_episode_forward import episodes,nonoverlap,write_csv,sha
from moat_param_lab import total_return_index
import backtest_valuation_strategy as bt
import build_historical_valuation_bands as bhv
import legacy
from slope import SlopeGuard


def main():
    manifest=json.loads((EXP/'manifest.json').read_text())
    bt.ACTIONS=bhv.ACTIONS=ROOT/manifest['current_reference_inputs']['data/raw/corporate_actions/a_share_corporate_actions.csv']
    actions=bt.load_actions();raw_actions=bhv.load_actions();legacy.bhv=bhv
    oldpath=ROOT/'data/experiments/exp_selection_edge/candidates.csv'
    previous=ROOT/'data/experiments/exp_ma_slope_20260914'
    # name -> candidate log, old MA?, old returns?, require corrected trend?, require slopes?
    specs={
      'OLD':(oldpath,True,True,False,False),
      'RETURN_FIX':(oldpath,True,False,False,False),
      'MA_FIX':(oldpath,False,True,False,False),
      'FIXED':(oldpath,False,False,False,False),
      'TREND_FIXED':(oldpath,False,False,True,False),
      'OLD_BOTH1':(oldpath,True,True,False,True),
      'FIXED_BOTH1':(oldpath,False,False,False,True),
      'TREND_BOTH1':(oldpath,False,False,True,True),
      'CURRENT_OLD':(previous/'signals/BASE/2011-11-01/candidates.csv',True,True,False,False),
      'CURRENT_OLD_BOTH1':(previous/'signals/BOTH1/2011-11-01/candidates.csv',True,True,False,False),
      'CURRENT_BASE':(EXP/'signals/BASE/2011-11-01/candidates.csv',False,False,False,False),
      'CURRENT_BOTH1':(EXP/'signals/BOTH1/2011-11-01/candidates.csv',False,False,False,False)}
    sources={Path(__file__),oldpath,bt.ACTIONS,ROOT/'scripts/backtest_valuation_strategy.py',
             ROOT/'scripts/experimental/moat_param_lab.py',ROOT/'scripts/experimental/pv_episode_forward.py',EXP/'legacy.py'}
    logs={}
    for name,(p,*_) in specs.items():
        sources.add(p);logs[name]=defaultdict(dict)
        for r in csv.DictReader(p.open()):
            if r['rank']=='1':
                c,d=r['security_code'],r['signal_date'];assert d not in logs[name][c];logs[name][c][d]=r
    before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    codes=set().union(*(set(x) for x in logs.values()))
    counts=defaultdict(int);obs=defaultdict(list);details=[];gates=defaultdict(lambda:dict(before=0,after=0))
    differences=[];slope_checks=0;original_affine=bt.exright_affine
    for c in sorted(codes):
        raw=bhv.load_ohlcv(c);prices=dict(raw);days=sorted(prices);di={d:i for i,d in enumerate(days)}
        sources.add(bhv.OHLCV_DIR/f'{c}.csv')
        before[str((bhv.OHLCV_DIR/f'{c}.csv').relative_to(ROOT))]=sha(bhv.OHLCV_DIR/f'{c}.csv')
        ev=actions.get(c,{})
        fixed_ma=bt.adjusted_moving_averages(prices,ev,(20,60))
        try:
            bt.exright_affine=legacy.exright_affine
            old_ma=bt.adjusted_moving_averages(prices,ev,(20,60))
        finally:bt.exright_affine=original_affine
        fixed_tr=total_return_index(raw,raw_actions.get(c,[]));old_tr=legacy.total_return_index(raw,raw_actions.get(c,[]))
        edays=sorted(ev);j=0;steps=[[] for _ in days]
        for i,d in enumerate(days):
            while j<len(edays) and edays[j]<=d:
                steps[i].append(ev[edays[j]]);j+=1
        guard=SlopeGuard({c:prices},{},{c:ev},{'lag':1,'windows':[20,60]})
        for name,(_,oldm,oldr,trend,slope) in specs.items():
            rows=logs[name].get(c,{})
            if not rows:continue
            assert set(rows)<=set(days)
            ma=old_ma if oldm else fixed_ma;tr=old_tr if oldr else fixed_tr
            eligible=[d in rows and (not trend or prices[d]>ma.get(d,{}).get(20,float('inf'))>ma.get(d,{}).get(60,float('inf')))
                      and (not slope or guard.allows(c,d)) for d in days]
            gates[name]['before']+=len(rows);gates[name]['after']+=sum(eligible)
            if name=='CURRENT_BOTH1':
                for d in rows:assert guard.allows(c,d),(c,d);slope_checks+=1
            m60=[ma.get(d,{}).get(60) for d in days]
            ep=episodes(eligible,[prices[d] for d in days],m60,steps)
            sp=episodes(eligible,[prices[d] for d in days],m60,steps,'stop')
            for h in (250,750):
                picks={'daily':[{'signal_i':i} for i,v in enumerate(eligible) if v],
                       'ma60_episode':ep,'ma60_nonoverlap':nonoverlap(ep,h),'stop_episode':sp}
                for method,es in picks.items():
                    key=name,method,h
                    for e in es:
                        sd=days[e['signal_i']];r=rows[sd];ed=r['exec_date'];start=di.get(ed)
                        end=start+h if start is not None else None;good=end is not None and end<len(days)
                        ret=tr[days[end]]/tr[ed]-1 if good else None
                        counts[key]+=1
                        if good:obs[key].append((c,sd[:4],ret))
                        b=e.get('break_i')
                        details.append(dict(arm=name,method=method,horizon=h,code=c,signal_date=sd,exec_date=ed,
                            end_date=days[end] if good else '',break_date=days[b] if b is not None else '',
                            complete=good,forward_return=ret))
    summaries=[];annual=[];company=[]
    for (name,method,h),n in sorted(counts.items()):
        xs=obs[name,method,h];cs=defaultdict(list);ys=defaultdict(list)
        for c,y,r in xs:cs[c].append(r);ys[y].append(r)
        vals=[r for c,y,r in xs]
        summaries.append(dict(arm=name,method=method,horizon=h,signals=n,complete=len(xs),codes=len(cs),missing=n-len(xs),
            median=st.median(vals),mean=st.mean(vals),positive_fraction=st.mean(v>0 for v in vals),
            median_of_code_medians=st.median([st.median(v) for v in cs.values()])))
        annual += [dict(arm=name,method=method,horizon=h,year=y,n=len(v),median=st.median(v)) for y,v in sorted(ys.items())]
        company += [dict(arm=name,method=method,horizon=h,code=c,n=len(v),median=st.median(v)) for c,v in sorted(cs.items())]
    reproduced=0
    for stage,mapping in [('old',{'OLD':'BASE','OLD_BOTH1':'BOTH1'}),('current',{'CURRENT_OLD':'BASE','CURRENT_OLD_BOTH1':'BOTH1'})]:
        prior=list(csv.DictReader((previous/f'signal_{stage}_summary.csv').open()))
        for r in summaries:
            if r['arm'] not in mapping:continue
            o=next(q for q in prior if q['arm']==mapping[r['arm']] and q['method']==r['method'] and int(q['horizon'])==r['horizon'])
            assert r['complete']==int(o['complete']) and abs(r['median']-float(o['median']))<1e-12,(r,o)
            reproduced+=1
    interval_checks=0
    groups=defaultdict(list)
    for r in details:
        if r['method']=='ma60_nonoverlap' and r['complete']:groups[r['arm'],r['horizon'],r['code']].append(r)
    for key,rs in groups.items():
        rs.sort(key=lambda r:r['signal_date'])
        for a,b in zip(rs,rs[1:]):assert b['exec_date']>=a['end_date'],key;interval_checks+=1
    for name,rows in [('summary',summaries),('annual',annual),('by_code',company),('observations',details)]:
        write_csv(EXP/f'signal_{name}.csv',rows)
    assert all(sha(ROOT/p)==h for p,h in before.items())
    save('signal_verification.json',dict(reproduced_old_groups=reproduced,nonoverlap_checks=interval_checks,
        current_slope_checks=slope_checks,gates=gates,inputs_unchanged=True,input_sha256=before,
        definitions={k:dict(path=str(v[0].relative_to(ROOT)),old_ma=v[1],old_return=v[2],require_trend=v[3],require_slope=v[4]) for k,v in specs.items()}))
    print(f'SIGNAL COMPLETE: {len(summaries)} groups, {reproduced} historical groups reproduced.',flush=True)


if __name__=='__main__':main()

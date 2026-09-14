"""Independent window-mean, execution, summary and interval checks after the run."""
import bisect
import csv
import json
import math
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from prepare import EXP,ROOT,sw,save
from slope import SlopeGuard
sys.path.insert(0,str(ROOT/'scripts/experimental'))
from delta_attribution import load_contrib
from pv_episode_forward import sha
import backtest_valuation_strategy as bt
import build_historical_valuation_bands as bhv


def read(p):return list(csv.DictReader(p.open()))

def main():
    manifest=json.loads((EXP/'manifest.json').read_text())
    bt.ACTIONS=ROOT/manifest['frozen_reference_inputs']['data/raw/corporate_actions/a_share_corporate_actions.csv']
    actions=bt.load_actions();spec=json.loads((EXP/'grid.json').read_text())[1]
    price_cache={};guard=SlopeGuard(price_cache,{},actions,spec)
    def get(code):
        if code not in price_cache:price_cache[code]=dict(bhv.load_ohlcv(code))
        return price_cache[code]
    summary_rows=read(EXP/'summary_rows.csv')
    transactions=[];attributions=[];checked_buys=0;independent=0;max_error=0
    for start in ('2009-11-01','2011-11-01'):
        contrib={}
        for arm in ('BASE','BOTH1'):
            row=next(r for r in summary_rows if r['group']=='full' and r['arm']==arm and r['start']==start)
            nav=read(EXP/'nav'/f"{row['nav_tag']}.csv");days=[r['date'] for r in nav];di={d:i for i,d in enumerate(days)}
            ledger=read(EXP/'signals'/arm/start/'ledger.csv')
            buys=[r for r in ledger if r['action']=='买入']
            if arm=='BOTH1':
                for r in buys:
                    i=di[r['date']];assert i>0;sd=days[i-1];c=r['security_code'];get(c)
                    assert guard.allows(c,sd),(start,c,sd,r)
                    checked_buys+=1
                subset=buys[:]
                random.Random(20260914).shuffle(subset)
                for r in subset[:80]:
                    sd=days[di[r['date']]-1];c=r['security_code'];p=get(c);ds=sorted(p);j=ds.index(sd)
                    for n,(a,b,slope) in guard.differences(c,sd).items():
                        # Independent full windows, not the entering/leaving identity used by the guard.
                        cur=st.mean(guard.rebase(c,p[d],d,sd) for d in ds[j-n+1:j+1])
                        prev=st.mean(guard.rebase(c,p[d],d,sd) for d in ds[j-n:j])
                        error=abs(cur-prev-slope);max_error=max(max_error,error)
                        assert error<1e-10,(c,sd,n,error)
                        independent+=1
            transactions.append(dict(start=start,arm=arm,buys=len(buys),sells=sum(r['action']=='卖出' for r in ledger),
                                     buy_days=len(set(r['date'] for r in buys)),
                                     buy_amount=sum(float(r['amount']) for r in buys)))
            files=list((EXP/'cache/full').glob(f"*{row['nav_tag']}_trades.csv"))
            assert len(files)==1,(row['nav_tag'],files)
            vals,relative=load_contrib(files[0]);assert relative
            contrib[arm]=vals
        a,b=contrib['BOTH1'],contrib['BASE'];codes=set(a)|set(b)
        attributions += [dict(start=start,code=c,base_contrib=b.get(c,0),slope_contrib=a.get(c,0),
                              delta_contrib=a.get(c,0)-b.get(c,0)) for c in sorted(codes)]
    count_checks=0;intervals=0
    for stage in ('old','current'):
        rows=read(EXP/f'signal_{stage}_observations.csv');summaries=read(EXP/f'signal_{stage}_summary.csv')
        for s in summaries:
            if s['arm'] not in ('BASE','BOTH1'):continue
            rs=[r for r in rows if (r['arm'],r['method'],r['horizon'])==(s['arm'],s['method'],s['horizon'])]
            vals=[float(r['forward_return']) for r in rs if r['complete']=='True']
            assert len(rs)==int(s['signals']) and len(vals)==int(s['complete'])
            assert abs(st.median(vals)-float(s['median']))<1e-12
            count_checks+=1
        groups=defaultdict(list)
        for r in rows:
            if r['method']=='ma60_nonoverlap' and r['complete']=='True':groups[r['arm'],r['horizon'],r['code']].append(r)
        for key,rs in groups.items():
            rs.sort(key=lambda r:r['signal_date'])
            for a,b in zip(rs,rs[1:]):assert b['exec_date']>=a['end_date'],key;intervals+=1
    from pv_episode_forward import write_csv
    write_csv(EXP/'transactions.csv',transactions);write_csv(EXP/'attribution.csv',attributions)
    stats={}
    for start in ('2009-11-01','2011-11-01'):
        vals=[r for r in attributions if r['start']==start]
        vals.sort(key=lambda r:abs(r['delta_contrib']),reverse=True)
        gross=sum(abs(r['delta_contrib']) for r in vals);net=sum(r['delta_contrib'] for r in vals)
        stats[start]=dict(net_delta_contrib=net,top3_absolute_share=sum(abs(r['delta_contrib']) for r in vals[:3])/gross,
                          largest_changes=vals[:8])
    save('extra_verification.json',dict(checked_actual_buys=checked_buys,independent_full_window_checks=independent,
         max_slope_error=max_error,signal_count_and_median_checks=count_checks,nonoverlap_adjacent_checks=intervals,
         attribution=stats,source_sha256={str(Path(__file__).relative_to(ROOT)):sha(Path(__file__))},))
    print('EXTRA VALIDATION COMPLETE:',checked_buys,'buys,',independent,'independent slopes,',count_checks,'signal summaries.',flush=True)


if __name__=='__main__':main()

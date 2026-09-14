"""Audit quote-calendar gaps and independently recompute affected MAs/returns."""
import bisect
import csv
import json
import math
import statistics as st
import sys
from prepare import EXP, ROOT, save, sw
sys.path.insert(0, str(ROOT/'scripts/experimental'))
import backtest_valuation_strategy as bt
import build_historical_valuation_bands as bhv
import legacy
from pv_episode_forward import return_indices, write_csv
from moat_param_lab import total_return_index
from slope import SlopeGuard


def main():
    manifest = json.loads((EXP/'manifest.json').read_text())
    bt.ACTIONS = bhv.ACTIONS = ROOT/manifest['current_reference_inputs']['data/raw/corporate_actions/a_share_corporate_actions.csv']
    actions = bt.load_actions(); raw_actions = bhv.load_actions(); legacy.bhv = bhv
    rows=[]; gaps=[]; checked=0; error=0; return_error=0; examples=[]
    current_affine = bt.exright_affine
    for code in sorted(manifest['price_ends']):
        raw = bhv.load_ohlcv(code)
        if not raw: continue
        prices=dict(raw);days=sorted(prices);positions={d:i for i,d in enumerate(days)};ev=actions.get(code,{})
        missing = [d for d in sorted(ev) if days[0]<d<=days[-1] and d not in prices]
        for d in missing:
            j=bisect.bisect_left(days,d)
            c,b,r,p=ev[d]
            gaps.append(dict(code=code,event_date=d,previous_quote=days[j-1],next_quote=days[j],cash=c,bonus=b,rights=r,subscription=p))
        oldret=legacy.daily_returns({code:prices},{code:ev})[code]
        newret=bt.daily_returns({code:prices},{code:ev})[code]
        changed_ret=sum(abs(newret[d]-oldret[d])>1e-12 for d in newret)
        oldtri=legacy.total_return_index(raw,raw_actions.get(code,[]))
        newtri=total_return_index(raw,raw_actions.get(code,[]))
        direct,_,_=return_indices(days,[prices[d] for d in days],ev)
        for i,d in enumerate(days):
            er=abs(newtri[d]/newtri[days[0]]-direct[i])/max(1,abs(direct[i]))
            return_error=max(return_error,er)
            assert er<1e-10,(code,d,er)
        if not missing:
            rows.append(dict(code=code,gap_events=0,ma20_changed=0,ma60_changed=0,trend_changed=0,
                             return_points_changed=changed_ret,checked_windows=0,
                             final_tri_old=oldtri[days[-1]]/oldtri[days[0]],final_tri_new=direct[-1]))
            continue
        try:
            bt.exright_affine=legacy.exright_affine
            oldma=bt.adjusted_moving_averages(prices,ev,(20,60))
        finally: bt.exright_affine=current_affine
        newma=bt.adjusted_moving_averages(prices,ev,(20,60))
        counts={n:sum(abs(newma[d][n]-oldma[d][n])>1e-9 for d in newma if n in newma[d]) for n in (20,60)}
        trend=lambda ma,d: prices[d]>ma.get(d,{}).get(20,float('inf'))>ma.get(d,{}).get(60,float('inf'))
        changed=sum(trend(newma,d)!=trend(oldma,d) for d in days)
        guard=SlopeGuard({code:prices},{},{code:ev},{'lag':1,'windows':[20,60]})
        indices=sorted({j for d in missing for j in range(bisect.bisect_left(days,d),min(len(days),bisect.bisect_left(days,d)+61))})
        local=0
        for i in indices:
            for n in (20,60):
                if i+1<n:continue
                value=st.mean(guard.rebase(code,prices[d],d,days[i]) for d in days[i-n+1:i+1])
                er=abs(value-newma[days[i]][n]);error=max(error,er)
                assert er<1e-8,(code,days[i],n,er)
                local+=1
                if code=='002128' and days[i]=='2017-08-14':
                    examples.append(dict(code=code,date=days[i],window=n,legacy=oldma[days[i]][n],fixed=newma[days[i]][n],independent=value))
        checked+=local
        rows.append(dict(code=code,gap_events=len(missing),ma20_changed=counts[20],ma60_changed=counts[60],
                         trend_changed=changed,return_points_changed=changed_ret,checked_windows=local,
                         final_tri_old=oldtri[days[-1]]/oldtri[days[0]],final_tri_new=direct[-1]))
    write_csv(EXP/'quote_gap_events.csv',gaps)
    write_csv(EXP/'affected_codes.csv',rows)
    save('event_audit.json',dict(codes=len(rows),gap_events=len(gaps),gap_codes=sum(r['gap_events']>0 for r in rows),
        changed_ma20=sum(r['ma20_changed'] for r in rows),changed_ma60=sum(r['ma60_changed'] for r in rows),
        changed_trend=sum(r['trend_changed'] for r in rows),changed_return_points=sum(r['return_points_changed'] for r in rows),
        independent_ma_windows=checked,max_ma_error=error,max_index_relative_error=return_error,example=examples))
    print(f'AUDIT COMPLETE: {len(gaps)} events without stock quotes; {checked} independent MA windows.',flush=True)


if __name__=='__main__':main()

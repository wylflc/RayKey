"""Independent accounting and coverage checks for the top-three statistics."""
import bisect
import calendar
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'scripts/experimental')]
import backtest_valuation_strategy as bt
import build_historical_valuation_bands as bhv
from panel_tier_forward import load_spans,in_span
from pv_episode_forward import sha

OUT=Path(__file__).parent
def read(name):
    with (OUT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main():
    manifest=json.loads((OUT/'manifest.json').read_text())
    for name,h in manifest['output_sha256'].items():assert sha(OUT/name)==h,name
    rows=read('daily_top3.csv');segments=read('segments_top3.csv')
    days=[d for d,p in bhv.load_ohlcv('INDEX_000300')]
    signal_days=[d for d in days if d>=manifest['since']]
    byday=defaultdict(list)
    for r in rows:byday[r['signal_date']].append(r)
    actions=bt.load_actions();prices={};raw={}
    def quotes(code):
        if code not in prices:
            raw[code]=bhv.load_ohlcv(code);prices[code]=dict(raw[code])
        return prices[code]
    def direct_ma(code,day,n):
        series=raw[code];di=bisect.bisect_left(series,(day,-math.inf))
        if di+1<n:return None
        values=[]
        for d,p in series[di+1-n:di+1]:
            for event,a in sorted(actions.get(code,{}).items()):
                if d<event<=day:
                    dividend,bonus,rights,subscription=a
                    p=(p-dividend+rights*subscription)/(1+bonus+rights)
            values.append(p)
        return statistics.mean(values)
    for day,rs in byday.items():
        assert [int(r['rank']) for r in rs]==list(range(1,len(rs)+1))
        assert [(float(r['pv']),r['security_code']) for r in rs]==sorted((float(r['pv']),r['security_code']) for r in rs)
        assert len(rs)==min(3,int(rs[0]['eligible_count']))
    spans=load_spans(ROOT/'data/processed/pit_attention/panel_moat_bank_v6b.csv')
    for r in rows:
        code=r['security_code'];p=quotes(code);day=r['signal_date']
        assert in_span(spans[code],day)
        assert 0<float(r['pv'])<=manifest['buy_line']
        assert float(r['signal_close'])>float(r['ma20'])>float(r['ma60'])
        ix=days.index(day)+1
        assert r['execution_date']==(days[ix] if ix<len(days) else '')
        for h in (1,3):
            if not r['execution_date']:
                assert r[f'status_{h}y']=='execution_after_cutoff';continue
            start=date.fromisoformat(r['execution_date']);year=start.year+h
            target=date(year,start.month,min(start.day,calendar.monthrange(year,start.month)[1])).isoformat()
            assert r[f'target_{h}y']==target
            ix=bisect.bisect_left(days,target);end=days[ix] if ix<len(days) else ''
            assert r[f'end_{h}y']==end
            if r[f'status_{h}y']=='complete':
                assert r['execution_date'] in p and end in p
                assert r[f'return_{h}y']!=''
            else:assert r[f'return_{h}y']==''
    grouped=defaultdict(list)
    for r in segments:grouped[int(r['segment_id'])].append(r)
    represented=[];prev=None
    for ident,rs in grouped.items():
        r=rs[0];members={x['security_code'] for x in rs if x['security_code']}
        assert members!=prev;prev=members
        ds=[d for d in signal_days if r['segment_start']<=d<=r['segment_end']]
        assert len(ds)==int(r['trading_days'])
        for d in ds:assert {x['security_code'] for x in byday[d]}==members
        for x in rs:
            if x['security_code']:
                source=next(a for a in byday[r['segment_start']] if a['security_code']==x['security_code'])
                assert all(x[k]==v for k,v in source.items())
        represented+=ds
    assert represented==signal_days
    # Rebuild full-universe ranks independently on deterministic dates spread
    # over the entire history, with direct event-by-event 20/60-day averages.
    sample_days=set(signal_days[::173]+signal_days[-1:]);expected=defaultdict(list);ma_checks=0
    with (ROOT/'data/processed/a_share_daily_states_adopted.csv').open(newline='') as f:
        reader=csv.reader(f);head=next(reader)
        ci,di,vi=[head.index(k) for k in ('security_code','date','valuation_ratio')]
        for r in reader:
            code,day=r[ci],r[di]
            if day not in sample_days or code not in spans or not r[vi] or not in_span(spans[code],day):continue
            pv=float(r[vi])
            if not 0<pv<=manifest['buy_line']:continue
            p=quotes(code);m20=direct_ma(code,day,20);m60=direct_ma(code,day,60);ma_checks+=2
            if m20 is not None and m60 is not None and p[day]>m20>m60:expected[day].append((pv,code))
    for day in sample_days:
        assert [(float(r['pv']),r['security_code']) for r in byday[day]]==sorted(expected[day])[:3],day
        if byday[day]:assert int(byday[day][0]['eligible_count'])==len(expected[day])
    # Direct shares/cash ledger, avoiding the cumulative return-index function.
    checked=0;max_error=0.0
    for h in (1,3):
        complete=[r for r in rows if r[f'status_{h}y']=='complete']
        sample=complete[::max(1,len(complete)//80)]
        for r in sample:
            code=r['security_code'];p=quotes(code);start=r['execution_date'];end=r[f'end_{h}y']
            events=sorted((d,a) for d,a in actions.get(code,{}).items() if start<d<=end)
            pointer=0;shares=1.0;cash=0.0
            for d,price in raw[code]:
                if not start<d<=end:continue
                while pointer<len(events) and events[pointer][0]<=d:
                    dividend,bonus,rights,subscription=events[pointer][1]
                    cash+=shares*(dividend-rights*subscription)
                    shares*=1+bonus+rights;pointer+=1
                shares+=cash/price;cash=0.0
            actual=(shares*p[end]+cash)/p[start]-1
            error=abs(actual-float(r[f'return_{h}y']));max_error=max(max_error,error)
            assert error<1e-9,(code,start,h,error)
            checked+=1
    groups={'daily_top3':rows,'segment_starts':[r for r in segments if r['security_code']],
            'quarterly_top3':[r for r in read('quarterly_top3.csv') if r['security_code']],
            'annual_top3':[r for r in read('annual_top3.csv') if r['security_code']],
            'ma60_episodes':read('ma60_episodes.csv')}
    for h in (1,3):
        groups['ma60_nonoverlap']=read(f'ma60_nonoverlap_{h}y.csv')
        last={}
        for r in sorted(groups['ma60_nonoverlap'],key=lambda r:r['execution_date']):
            code=r['security_code'];assert r['execution_date']>=last.get(code,'')
            last[code]=r[f'end_{h}y'] or r[f'target_{h}y']
        for summary in read('summary.csv'):
            if summary['years']!=str(h):continue
            rs=groups[summary['group']];good=[r for r in rs if r[f'status_{h}y']=='complete']
            assert len(rs)==int(summary['signals']) and len(good)==int(summary['complete'])
            assert len({r['security_code'] for r in good})==int(summary['complete_companies'])
            assert abs(statistics.median(float(r[f'return_{h}y']) for r in good)-float(summary['median_return']))<1e-12
    result={'passed':True,'daily_rows_checked':len(rows),'segments_checked':len(grouped),
            'full_universe_rank_dates':len(sample_days),'direct_ma_windows':ma_checks,
            'independent_cash_ledgers':checked,'max_return_error':max_error,
            'summary_groups_checked':len(read('summary.csv')),
            'source_manifest_sha256':sha(OUT/'manifest.json')}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()

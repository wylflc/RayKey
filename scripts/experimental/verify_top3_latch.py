"""Independent interval-based audit of signal activation and stop resets."""
import bisect
import csv
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def verify_latched(manifest,byday,days,signal_days,quotes,raw,actions,direct_ma,out):
    import backtest_valuation_strategy as bt
    from panel_tier_forward import load_spans,in_span
    spans=load_spans(ROOT/'data/processed/pit_attention/panel_moat_bank_v6b.csv')
    cheap=defaultdict(dict)
    with (ROOT/'data/processed/a_share_daily_states_adopted.csv').open(newline='') as f:
        reader=csv.reader(f);head=next(reader)
        ci,di,vi=[head.index(k) for k in ('security_code','date','valuation_ratio')]
        for r in reader:
            code,day=r[ci],r[di]
            if code not in spans or not manifest['since']<=day<=manifest['cutoff'] or not r[vi]:continue
            pv=float(r[vi])
            if 0<pv<=manifest['buy_line'] and in_span(spans[code],day):cheap[code][day]=pv
    expected=defaultdict(list);details={};cycles=[];ma_checks=0
    sample_days=set(signal_days[::173]+signal_days[-1:])
    for code,cheap_days in sorted(cheap.items()):
        p=quotes(code);ds=[d for d,price in raw[code] if d<=manifest['cutoff']]
        mas=bt.adjusted_moving_averages(p,actions.get(code,{}),windows=(20,60))
        full=[]
        for d in cheap_days:
            m=mas.get(d,{})
            if d in sample_days and 60 in m:
                for n in (20,60):
                    assert abs(direct_ma(code,d,n)-m[n])<1e-7,(code,d,n)
                    ma_checks+=1
            if 60 in m and p[d]>m[20]>m[60]:full.append(d)
        full.sort();fi=0
        # Process one complete activation interval at a time. A new interval
        # can only start at a full signal after the previous stop reset.
        while fi<len(full):
            activated=full[fi];i=bisect.bisect_left(ds,activated)
            anchor_day=ds[i+1] if i+1<len(ds) else ''
            original=mas[anchor_day][60] if anchor_day else None
            reset=''
            for j in range(i,len(ds)):
                d=ds[j];m=mas[d]
                anchor=None
                if j>i:
                    # Recompute from the original anchor independently at each
                    # quote, including events on dates without any quote.
                    anchor=original
                    for event,(dividend,bonus,rights,subscription) in sorted(actions.get(code,{}).items()):
                        if anchor_day<event<=d:anchor=(anchor-dividend+rights*subscription)/(1+bonus+rights)
                    if p[d]<min(anchor,m[60]):
                        reset=d
                        break
                if d in cheap_days and m[20]>m[60]:
                    expected[d].append((cheap_days[d],code))
                    details[code,d]=(activated,anchor_day if j>i else '',anchor,min(anchor,m[60]) if anchor is not None else None)
            cycles.append((code,activated,anchor_day,reset))
            if not reset:break
            fi=bisect.bisect_left(full,reset)
    for day in signal_days:
        actual=[(float(r['pv']),r['security_code']) for r in byday.get(day,[])]
        assert actual==sorted(expected[day])[:3],('ranking',day,actual,sorted(expected[day])[:3])
        for r in byday.get(day,[]):
            assert int(r['eligible_count'])==len(expected[day])
            activated,anchor_day,anchor,stop=details[r['security_code'],day]
            assert r['activation_date']==activated and r['anchor_date']==anchor_day
            for key,v in [('stop_anchor',anchor),('stop_line',stop)]:
                assert r[key]=='' if v is None else abs(float(r[key])-v)<1e-9
            kind='initial' if activated==day else 'continued' if float(r['signal_close'])>float(r['ma20']) else 'continued_below_ma20'
            assert r['qualification']==kind
    with (out/'activation_cycles.csv').open(encoding='utf-8-sig',newline='') as f:
        actual_cycles=list(csv.DictReader(f))
    assert sorted(cycles)==sorted((r['security_code'],r['activation_date'],r['anchor_date'],r['reset_date']) for r in actual_cycles)
    # Strict baseline still reproduces every archived day's top three with the
    # exact same input data; separate actual correction from data/version drift.
    strict_path=ROOT/'data/experiments/exp_top3_periods_20260915/daily_top3.csv'
    with strict_path.open(encoding='utf-8-sig',newline='') as f:
        strict=defaultdict(list)
        for r in csv.DictReader(f):strict[r['signal_date']].append((float(r['pv']),r['security_code']))
    for day in signal_days:
        full_expected=[]
        for pv,code in expected[day]:
            p=quotes(code)
            # Direct baseline membership can be reconstructed from the strict
            # condition carried by the same day's qualifying signal records.
            if p[day]>bt_mas_cached(code,quotes,actions,bt)[day][20]:full_expected.append((pv,code))
        assert sorted(full_expected)[:3]==strict.get(day,[]),('strict_baseline',day)
    return len(signal_days),ma_checks,len(cycles)


_MA_CACHE={}
def bt_mas_cached(code,quotes,actions,bt):
    if code not in _MA_CACHE:
        _MA_CACHE[code]=bt.adjusted_moving_averages(quotes(code),actions.get(code,{}),windows=(20,60))
    return _MA_CACHE[code]


def verify_ma60_counting(rows,episodes,quotes,raw,actions,cutoff):
    import backtest_valuation_strategy as bt
    bycode=defaultdict(list)
    for r in rows:bycode[r['security_code']].append(r)
    expected=set()
    for code,rs in bycode.items():
        p=quotes(code);ma=bt_mas_cached(code,quotes,actions,bt)
        breaks=[d for d,price in raw[code] if d<=cutoff and 60 in ma.get(d,{}) and price<ma[d][60]]
        seen=set()
        for r in rs:
            d=r['signal_date'];i=bisect.bisect_left(breaks,d)
            if i<len(breaks) and breaks[i]==d:
                key=('below',d);end=d
            else:
                key=('above',i);end=breaks[i] if i<len(breaks) else ''
            if key not in seen:
                seen.add(key);expected.add((code,d,end))
    actual={(r['security_code'],r['signal_date'],r['ma60_break_date']) for r in episodes}
    assert actual==expected,'MA60 counting boundary mismatch'

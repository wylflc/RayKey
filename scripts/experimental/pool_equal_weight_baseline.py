"""宇宙等权、月度再平衡、含分红拆股的买入持有：池的贡献基线。"""
import csv, sys, datetime as dt
from collections import defaultdict
from pathlib import Path
ROOT=Path('/gpfs/work1/0/qt15419/zwang/mm_quant/RayKey')
def load_actions(p):
    a=defaultdict(dict)
    for r in csv.DictReader(open(p,encoding='utf-8')):
        d=r['ex_dividend_date']
        if not d: continue
        cash=float(r['cash_per_share'] or 0); ratio=float(r['share_ratio'] or 0)
        c,s=a[r['security_code']].get(d,(0.0,0.0)); a[r['security_code']][d]=(c+cash, s+ratio)
    return a
def daily_returns(path, acts):
    rows=list(csv.DictReader(open(path)))
    out={}; prev=None
    for r in rows:
        try: c=float(r['close'])
        except: continue
        if c<=0: continue
        d=r['date']
        if prev is not None:
            cash,ratio=acts.get(d,(0.0,0.0))
            out[d]=(c*(1+ratio)+cash)/prev-1
        prev=c
    return out
def run(market, start, end):
    if market=='us':
        panel=ROOT/'data/processed/pit_attention/panel_sp500_us.csv'; ohlcv=ROOT/'data/raw/ohlcv_us'; acts=load_actions(ROOT/'data/raw/corporate_actions/us_corporate_actions.csv')
        panels={'sp500':panel,'sp100':ROOT/'data/processed/pit_attention/panel_sp100_us.csv'}
    else:
        ohlcv=ROOT/'data/raw/ohlcv'; acts=load_actions(ROOT/'data/raw/corporate_actions/a_share_corporate_actions.csv')
        panels={'v6b':ROOT/'data/processed/pit_attention/panel_moat_bank_v6b.csv'}
    for name,pp in panels.items():
        members=defaultdict(list)
        for r in csv.DictReader(open(pp)):
            members[r['security_code']].append((r['effective_from'], r['effective_to'] or '9999-12-31'))
        rets={}
        for code in members:
            f=ohlcv/f'{code}.csv'
            if f.exists(): rets[code]=daily_returns(f, acts.get(code,{}))
        # 月度等权：月初成员集合（在区间内且当月有行情），月内各自复利，月末再平衡
        days=sorted({d for r in rets.values() for d in r if start<=d<=end})
        months=defaultdict(list)
        for d in days: months[d[:7]].append(d)
        nav=1.0; peak=1.0; mdd=0.0; navs=[]
        for m in sorted(months):
            ds=months[m]; m0=ds[0]
            act=[c for c,iv in members.items() if c in rets and any(a<=m0<=b for a,b in iv) and any(d in rets[c] for d in ds)]
            if not act: continue
            w=1/len(act); month_ret=0.0
            for c in act:
                g=1.0
                for d in ds:
                    if d in rets[c]: g*=1+rets[c][d]
                month_ret+=w*(g-1)
            nav*=1+month_ret; peak=max(peak,nav); mdd=min(mdd,nav/peak-1); navs.append((ds[-1],nav,len(act)))
        yrs=(dt.date.fromisoformat(navs[-1][0])-dt.date.fromisoformat(start)).days/365.25
        print(f"{market}/{name} {start}→{navs[-1][0]}: 等权月再平衡 CAGR {(nav**(1/yrs)-1)*100:.2f}%  MDD {mdd*100:.1f}%  成员数 {min(n for _,_,n in navs)}~{max(n for _,_,n in navs)}")
for start in ['2012-05-01','2014-05-01','2016-05-01']:
    run('us', start, '2026-09-04')
    run('a', start, '2026-08-28')

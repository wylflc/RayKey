"""Causal total-exposure caps from current holdings; contract: preregister.md."""
import bisect
import math
import numpy as np

NORMAL = 1.666


def combine(a, b):
    vals=[x for x in (a,b) if x is not None]
    return min(vals) if vals else None


class ReturnPanel:
    def __init__(self, returns, dates):
        self.dates=sorted(dates)
        self.codes=sorted(returns); self.col={c:i for i,c in enumerate(self.codes)}
        self.values=np.zeros((len(self.dates),len(self.codes)))
        self.observed=np.zeros(self.values.shape,dtype=bool)
        dayidx={d:i for i,d in enumerate(self.dates)}
        for code, series in returns.items():
            for d,r in series.items():
                if d in dayidx:
                    i,j=dayidx[d],self.col[code]
                    self.values[i,j]=r; self.observed[i,j]=True

    def risk(self, weights, day, windows):
        end=bisect.bisect_right(self.dates,day)
        if not weights: return None, 1.0
        if any(c not in self.col for c in weights): return None, 0.0
        cols=[self.col[c] for c in weights]
        w=np.array(list(weights.values()))
        risks=[]; coverage=1.
        for n in windows:
            if end < n: return None, 0.
            obs=self.observed[end-n:end,cols]
            cov=float(w @ (obs.sum(axis=0)>=math.ceil(n*.9)))
            coverage=min(coverage,cov)
            if cov < .95-1e-12: return None,coverage
            portfolio=self.values[end-n:end,cols] @ w
            risks.append(float(np.std(portfolio,ddof=1))*math.sqrt(244))
        return max(risks),coverage


class RiskPolicy:
    def __init__(self,spec):
        self.spec=spec; self.previous=None; self.panel=None
        self.weights={}; self.snapshot_day=''; self.last={}

    def observe(self, day, market_values, panel):
        assert not self.snapshot_day or day>self.snapshot_day
        total=sum(market_values.values())
        self.weights={c:v/total for c,v in market_values.items() if v>0} if total else {}
        self.snapshot_day=day; self.panel=panel

    def resolve(self, day):
        assert not self.snapshot_day or self.snapshot_day<=day, 'future holdings'
        spec=self.spec; kind=spec['kind']
        q3=sum(sorted(self.weights.values(),reverse=True)[:3]) if self.weights else 1.
        raw=None; sigma=None; coverage=1.; missing=False
        if kind=='fixed': raw=spec['cap']
        if kind in ('stress','joint'): raw=spec['budget']/(.2*q3)
        if kind in ('vol','joint') and self.weights:
            sigma,coverage=self.panel.risk(self.weights,day,spec['windows'])
            missing=sigma is None
            v=(spec['floor'] if missing else max(spec['floor'],spec['target']/sigma)
               if sigma>0 else None)
            raw=combine(raw,v)
        if raw is not None and raw>=NORMAL: raw=None
        desired=(math.floor((raw+1e-10)*10)/10 if raw is not None else None)
        if kind=='fixed': desired=raw
        cap=desired
        if kind!='fixed' and self.previous is not None:
            if desired is None or desired>self.previous:
                raised=round(self.previous+.1,10)
                cap=(None if raised>=NORMAL else raised) if desired is None else min(desired,raised)
        self.previous=cap
        self.last=dict(signal_day=day,snapshot_day=self.snapshot_day,top3_stock_share=q3,
            unit_vol=sigma if sigma is not None else '',coverage=coverage,missing=missing,
            raw_cap=raw if raw is not None else '',risk_cap=cap if cap is not None else '')
        return cap


class CombinedConstraint:
    def __init__(self, original, policy):
        self.original=original; self.policy=policy; self.last={}

    def __getattr__(self,name): return getattr(self.original,name)

    def resolve(self,day):
        signal,base=self.original.resolve(day)
        risk=self.policy.resolve(day)
        combined=combine(base,risk)
        self.last=dict(**self.policy.last,base_cap=base if base is not None else '',
                       combined_cap=combined if combined is not None else '',
                       risk_dominant=risk is not None and (base is None or risk<base))
        return signal,combined

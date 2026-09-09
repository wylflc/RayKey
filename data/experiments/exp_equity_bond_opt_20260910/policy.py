"""Monthly, causal financing policies; research specification: preregister.md."""
from bisect import bisect_left, bisect_right
import csv
from datetime import date
import math
from pathlib import Path
import statistics
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from equity_bond_constraint import EquityBondConstraint


def grid():
    rows = [dict(arm='BASE', kind='baseline'), dict(arm='OFF', kind='control'),
            dict(arm='FIX100', kind='fixed', cap=1.)]
    for cap in (0., .3, .5, .8, 1.):
        for release in (.03, .035, .04, .045, .05):
            if cap == 1. and release == .03:
                continue
            rows.append(dict(arm=f'C{round(cap*100):03}R{round(release*1000):02}',
                             kind='hysteresis', cap=cap, release=release))
    for pe in (14, 16, 18, 20):
        rows.append(dict(arm=f'PE{pe}', kind='pe', threshold=pe))
    for q in (.7, .8, .9):
        rows.append(dict(arm=f'PEQ{round(q*100)}', kind='pe_q', threshold=q))
    for ratio in (1.2, 1.4, 1.6):
        rows.append(dict(arm=f'MA60X{round(ratio*100)}', kind='price_ma', threshold=ratio))
    for cap in (1.2, 1.4, 1.6):
        rows.append(dict(arm=f'PART{round(cap*100)}', kind='partial', cap=cap))
    for ma in (6, 10, 12):
        rows.append(dict(arm=f'TREND{ma:02}', kind='trend', ma=ma))
    for months in (2, 3):
        rows.append(dict(arm=f'CONFIRM{months}', kind='confirm', months=months))
    assert len(rows) == 45
    return rows


def features(macro_path, price_path):
    with Path(price_path).open() as f:
        prices = list(csv.DictReader(f))
    assert prices and all(a['date'] < b['date'] for a, b in zip(prices, prices[1:]))
    complete = {}
    for r in prices:
        close = float(r['close'])
        if not math.isfinite(close) or close <= 0:
            raise ValueError('Invalid index close')
        # The last cached month may be partial: never treat it as complete.
        if r['date'][:7] < prices[-1]['date'][:7]:
            complete[r['date'][:7]] = (r['date'], close)
    monthly = list(complete.values())
    days = [r[0] for r in monthly]
    with Path(macro_path).open(encoding='utf-8-sig') as f:
        macro = list(csv.DictReader(f))
    out = []
    pe_history = []
    for r in macro:
        day, pe = r['observed_on'], float(r['pe_ttm'])
        hist = sorted(pe_history[-60:])
        q = ((bisect_left(hist, pe) + bisect_right(hist, pe)) / (2*len(hist))
             if len(hist) >= 12 else None)
        pe_history.append(pe)
        i = bisect_right(days, day)
        available = monthly[:i]
        current = available[-1] if available else None
        fresh = current is not None and (date.fromisoformat(day)-date.fromisoformat(current[0])).days <= 45
        row = dict(observed_on=day, pe=pe, pe_q=q, index_day=current[0] if current else '',
                   index_close=current[1] if current else None, price_fresh=fresh)
        for n in (6, 10, 12, 60):
            valid = fresh and len(available) >= n
            if valid:
                a, b = date.fromisoformat(available[-n][0]), date.fromisoformat(available[-1][0])
                valid = (b.year-a.year)*12+b.month-a.month == n-1
            row[f'ma{n}'] = statistics.fmean(v for _, v in available[-n:]) if valid else None
        out.append(row)
    return out


def compute_caps(signals, rows, spec):
    """Precompute the entire state history, so account start and query order cannot reset it."""
    caps, audit = [], []
    active, streak = False, 0
    kind = spec['kind']
    for signal, f in zip(signals, rows, strict=True):
        assert signal.observed_on == f['observed_on']
        low = signal.spread < .03
        base = 1. if low else None
        fallback = False
        if kind == 'baseline':
            cap = base
        elif kind == 'control':
            cap = None
        elif kind == 'fixed':
            cap = spec['cap']
        elif kind == 'partial':
            cap = spec['cap'] if low else None
        elif kind == 'pe':
            cap = 1. if f['pe'] >= spec['threshold'] else None
        elif kind == 'pe_q':
            fallback = f['pe_q'] is None
            cap = base if fallback else (1. if f['pe_q'] >= spec['threshold'] else None)
        elif kind == 'price_ma':
            fallback = f['ma60'] is None
            cap = base if fallback else (1. if f['index_close']/f['ma60'] >= spec['threshold'] else None)
        elif kind in ('hysteresis', 'confirm', 'trend'):
            streak = 0 if low else streak + 1
            if low:
                active = True
            elif kind == 'hysteresis' and signal.spread >= spec['release']:
                active = False
            elif kind == 'confirm' and streak >= spec['months']:
                active = False
            elif kind == 'trend':
                fallback = f[f'ma{spec["ma"]}'] is None
                if fallback or f['index_close'] >= f[f'ma{spec["ma"]}']:
                    active = False
            cap = (spec.get('cap', 1.) if active else None)
            if fallback:
                cap = base
        else:
            raise ValueError(kind)
        caps.append(cap)
        audit.append(dict(**f, spread=signal.spread, cap=cap, fallback=fallback))
    return caps, audit


class ResearchConstraint(EquityBondConstraint):
    def __init__(self, path, *args, spec, price_path=None, **kwargs):
        super().__init__(path, *args, **kwargs)
        self.rows = features(path, price_path or ROOT/'data/raw/ohlcv/INDEX_000300.csv')
        self.caps, self.audit = compute_caps(self.signals, self.rows, spec)
        self.mode = 'cap'

    def resolve(self, signal_day):
        signal, _ = super().resolve(signal_day)  # retain all production date/data validation
        if signal is None:
            return None, None
        return signal, self.caps[bisect_right(self.days, signal_day)-1]

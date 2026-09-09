"""Research-only equity/bond exposure signal; specification: workflow §12.1."""
from bisect import bisect_left, bisect_right, insort
from collections import deque
import csv
from dataclasses import dataclass
from datetime import date
import math
from pathlib import Path


@dataclass(frozen=True)
class EquityBondSignal:
    observed_on: str
    spread: float
    percentile: float | None
    history_count: int


class EquityBondConstraint:
    def __init__(self, path, mode='cap', metric='percentile', threshold=.3,
                 lower=0.0, upper=1.6, ramp_high=.8, window=60, min_obs=12):
        if mode not in ('cap', 'credit', 'ramp') or metric not in ('spread', 'percentile'):
            raise ValueError('Invalid equity/bond mode or metric')
        if not all(math.isfinite(v) for v in (threshold, lower, upper, ramp_high)):
            raise ValueError('Equity/bond parameters must be finite')
        if not 0 <= lower <= upper <= 1.6:
            raise ValueError('Exposure bounds must satisfy 0 <= lower <= upper <= 1.6')
        if not 1 <= min_obs <= window:
            raise ValueError('Require 1 <= min_obs <= window')
        if metric == 'percentile' and not 0 <= threshold <= 1:
            raise ValueError('Percentile threshold must be in [0, 1]')
        if mode == 'ramp' and (metric != 'percentile' or not threshold < ramp_high <= 1):
            raise ValueError('Ramp requires percentile and threshold < ramp_high <= 1')
        self.mode, self.metric, self.threshold = mode, metric, threshold
        self.lower, self.upper, self.ramp_high = lower, upper, ramp_high
        self.days, self.signals = [], []
        ordered, history = [], deque()
        with Path(path).open(newline='', encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                day = row['observed_on']; dt = date.fromisoformat(day)
                if self.days and day <= self.days[-1]:
                    raise ValueError('Equity/bond observations must be unique and sorted')
                bond_day = date.fromisoformat(row['bond_observed_on'])
                pe, bond = float(row['pe_ttm']), float(row['bond_yield'])
                if not math.isfinite(pe) or pe <= 0 or not math.isfinite(bond) or not -.05 <= bond <= .3:
                    raise ValueError(f'Invalid PE or decimal bond yield: {day}')
                if not 0 <= (dt - bond_day).days <= 10:
                    raise ValueError(f'Future or stale bond observation: {day}')
                spread = 1. / pe - bond
                q = ((bisect_left(ordered, spread) + bisect_right(ordered, spread)) / (2 * len(ordered))
                     if len(ordered) >= min_obs else None)
                self.days.append(day)
                self.signals.append(EquityBondSignal(day, spread, q, len(ordered)))
                history.append(spread); insort(ordered, spread)
                if len(history) > window:
                    ordered.pop(bisect_left(ordered, history.popleft()))
        if not self.days:
            raise ValueError('Empty equity/bond data')

    def resolve(self, signal_day):
        i = bisect_right(self.days, signal_day) - 1
        if i < 0:
            return None, None
        signal = self.signals[i]
        if (date.fromisoformat(signal_day) - date.fromisoformat(signal.observed_on)).days > 45:
            raise ValueError(f'Stale equity/bond observation on {signal_day}')
        value = signal.spread if self.metric == 'spread' else signal.percentile
        if value is None:
            return signal, None
        if self.mode == 'ramp':
            weight = max(0., min(1., (value - self.threshold) / (self.ramp_high - self.threshold)))
            cap = self.lower + weight * (self.upper - self.lower)
        else:
            cap = self.lower if value < self.threshold else self.upper
        return signal, cap

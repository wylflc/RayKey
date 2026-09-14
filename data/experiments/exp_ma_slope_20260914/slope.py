"""Exact MA slope from entering/leaving prices, including suspended ex-dates."""
import bisect
import math


class SlopeGuard:
    def __init__(self, prices, mas, actions, spec):
        # Existing engine MAs are deliberately not used for this added gate:
        # their quote-date affine map can omit actions during a suspension.
        self.prices, self.actions, self.spec = prices, actions, spec
        self.calendars, self.event_days, self.cache = {}, {}, {}

    def rebase(self, code, value, start, end):
        if code not in self.event_days:
            self.event_days[code] = sorted(self.actions.get(code, {}))
        ds = self.event_days[code]
        for d in ds[bisect.bisect_right(ds, start):bisect.bisect_right(ds, end)]:
            cash, bonus, rights, price = self.actions[code][d]
            value = (value - cash + rights * price) / (1 + bonus + rights)
        return value

    def differences(self, code, day):
        """{N: (entering contribution, leaving contribution, per-day slope)}.

        MA_N(t)-MA_N(t-k) equals sum(P[t-j]-P[t-N-j], j<k)/N.
        All prices are rebased to t using all events, even when no quote exists.
        """
        if code not in self.calendars:
            self.calendars[code] = sorted(self.prices.get(code, {}))
        ds = self.calendars[code]
        i = bisect.bisect_left(ds, day)
        lag = self.spec['lag']
        if i >= len(ds) or ds[i] != day or i < lag:
            return None
        values = {}
        for n in self.spec['windows']:
            if i < n + lag - 1:
                return None
            entering = math.fsum(self.rebase(code, self.prices[code][ds[i-j]], ds[i-j], day) for j in range(lag))/n
            leaving = math.fsum(self.rebase(code, self.prices[code][ds[i-n-j]], ds[i-n-j], day) for j in range(lag))/n
            if not math.isfinite(entering) or not math.isfinite(leaving):
                return None
            values[n] = (entering, leaving, (entering-leaving)/lag)
        return values

    def allows(self, code, day):
        if not self.spec['lag']:
            return True
        key = code, day
        if key not in self.cache:
            values = self.differences(code, day)
            self.cache[key] = values is not None and all(
                a > b and not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-10)
                for a,b,d in values.values())
        return self.cache[key]

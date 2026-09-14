"""Signal-date MA slope in a common corporate-action basis; research only."""
import bisect
import math


class SlopeGuard:
    def __init__(self, prices, mas, actions, spec):
        self.prices, self.mas, self.actions, self.spec = prices, mas, actions, spec
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
        if code not in self.calendars:
            self.calendars[code] = sorted(self.prices.get(code, {}))
        ds = self.calendars[code]
        i = bisect.bisect_left(ds, day)
        lag = self.spec['lag']
        if i >= len(ds) or ds[i] != day or i < lag:
            return None
        current = self.mas.get(code, {}).get(day, {})
        previous = self.mas.get(code, {}).get(ds[i-lag], {})
        values = {}
        for w in self.spec['windows']:
            if w not in current or w not in previous:
                return None
            a, b = current[w], self.rebase(code, previous[w], ds[i-lag], day)
            if not math.isfinite(a) or not math.isfinite(b):
                return None
            values[w] = (a, b, (a-b)/lag)
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

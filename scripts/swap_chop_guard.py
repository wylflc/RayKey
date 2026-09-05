"""Research-only MA whipsaw guards. All decisions use signal-date information."""
from __future__ import annotations

import bisect
from dataclasses import dataclass


@dataclass(frozen=True)
class ChopConfig:
    mode: str = "off"
    depth: float = 0.02
    days: int = 3
    slope: float = 0.005
    crosses: int = 4
    cooldown: int = 5
    progress: float = 0.005

    def __post_init__(self):
        if self.mode not in ("off", "flat", "repeat", "repeat-flat"):
            raise ValueError("unknown chop mode")
        if not 0 < self.depth < 1 or not 0 <= self.slope < 1 or not 0 <= self.progress < 1:
            raise ValueError("chop depth/slope/progress must be fractions in [0,1), depth > 0")
        if not 2 <= self.days <= 20 or not 0 <= self.crosses <= 19 or self.cooldown < 1:
            raise ValueError("chop days in [2,20], crosses in [0,19], cooldown >= 1")


class ChopGuard:
    def __init__(self, config, prices, mas, actions, ma_window=20):
        self.config, self.prices, self.mas = config, prices, mas
        self.actions, self.ma_window = actions, ma_window
        self.calendars = {}
        self.event_days = {}
        self.recent = {}  # code -> (holding object, execution day index, signal day, signal close)

    def rebase(self, code, value, start, end):
        """Bring a historical price/MA to end-date basis; exclude future actions."""
        if code not in self.event_days:
            self.event_days[code] = sorted(self.actions.get(code, {}))
        ds = self.event_days[code]
        for day in ds[bisect.bisect_right(ds, start):bisect.bisect_right(ds, end)]:
            cash, bonus, rights, price = self.actions[code][day]
            value = (value - cash + rights * price) / (1 + bonus + rights)
        return value

    def features(self, code, signal_day):
        if code not in self.calendars:
            self.calendars[code] = sorted(self.prices.get(code, {}))
        ds = self.calendars[code]
        i = bisect.bisect_left(ds, signal_day)
        if i >= len(ds) or ds[i] != signal_day:
            return None
        series, ma = self.prices[code], self.mas.get(code, {})
        m = ma.get(signal_day, {}).get(self.ma_window)
        if not m or m <= 0:
            return None
        flags = []
        for d in ds[max(0, i - 19):i + 1]:
            md = ma.get(d, {}).get(self.ma_window)
            flags.append(None if not md else series[d] < md)
        run = 0
        for flag in reversed(flags):
            if flag is not True:
                break
            run += 1
        cross = sum(a is not None and b is not None and a != b for a, b in zip(flags, flags[1:]))
        slope = None
        if i >= 5 and (previous := ma.get(ds[i - 5], {}).get(self.ma_window)):
            previous = self.rebase(code, previous, ds[i - 5], signal_day)
            if previous > 0:
                slope = m / previous - 1
        return dict(close=series[signal_day], gap=series[signal_day] / m - 1,
                    run=run, cross=cross, slope=slope,
                    complete=len(flags) == 20 and all(f is not None for f in flags))

    def blocked(self, code, signal_day, day_no, lot):
        cfg = self.config
        ft = self.features(code, signal_day)
        if not ft or not (-cfg.depth < ft["gap"] < 0) or ft["run"] >= cfg.days:
            return ""
        if cfg.mode in ("flat", "repeat-flat"):
            if (not ft["complete"] or ft["slope"] is None or abs(ft["slope"]) > cfg.slope
                    or ft["cross"] < cfg.crosses):
                return ""
        if cfg.mode.startswith("repeat"):
            last = self.recent.get(code)
            if not last or last[0] is not lot or day_no > last[1] + cfg.cooldown:
                return ""
            previous = self.rebase(code, last[3], last[2], signal_day)
            if previous <= 0 or ft["close"] <= previous * (1 - cfg.progress):
                return ""
        return (f"chop:{cfg.mode};gap={ft['gap']:.5f};run={ft['run']};"
                f"slope={ft['slope']};cross={ft['cross']}") if cfg.mode != "off" else ""

    def record_sale(self, code, signal_day, day_no, lot, net_shares):
        if net_shares > 1e-9:
            self.recent[code] = (lot, day_no, signal_day, self.prices[code][signal_day])

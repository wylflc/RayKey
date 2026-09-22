"""Exploratory return/event audit; no strategy calibration or production writes.

Run from any directory. Frozen public responses live beside this script in
evidence_20260922_intel/. US sessions are aligned to the first subsequent
A-share session, avoiding same-calendar-day look-ahead. Percentages use
adjusted closes; OHLC observations use Tencent's current qfq basis.
"""

import bisect
import csv
import datetime as dt
import json
import math
import statistics as stats
from pathlib import Path


ROOT = Path(__file__).resolve().parent / "evidence_20260922_intel"
START, END = "2025-01-01", "2026-09-22"


def a_prices(symbol):
    response = json.loads((ROOT / f"{symbol}.json").read_text())
    data = response["payload"]["data"][f"sh{symbol}"]
    rows = data.get("qfqday", data.get("day", []))
    assert len({r[0] for r in rows}) == len(rows)
    return {r[0]: [float(v) for v in r[1:6]] for r in rows if START <= r[0] <= END}


def us_prices(symbol):
    response = json.loads((ROOT / f"{symbol}.json").read_text())
    data = response["payload"]["chart"]["result"][0]
    closes = data["indicators"]["adjclose"][0]["adjclose"]
    return {
        dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(): c
        for t, c in zip(data["timestamp"], closes)
        if c is not None and START <= dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat() < END
    }


def correlation(x, y):
    mx, my = stats.mean(x), stats.mean(y)
    denominator = math.sqrt(sum((v - mx) ** 2 for v in x) * sum((v - my) ** 2 for v in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / denominator if denominator else None


def describe(values):
    return {"n": len(values), "mean_pct": stats.mean(values) * 100,
            "median_pct": stats.median(values) * 100,
            "positive_count": sum(v > 0 for v in values)}


def write_csv(name, rows):
    with (ROOT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    a, benchmark = a_prices("688008"), a_prices("588000")
    intel, soxx = us_prices("INTC"), us_prices("SOXX")
    dates, us_dates = sorted(a), sorted(intel)
    assert set(dates) <= set(benchmark) and set(us_dates) <= set(soxx)
    assert dates[-1] == END and us_dates[-1] == "2026-09-21"
    ar = {i: a[d][1] / a[dates[i - 1]][1] - 1 for i, d in enumerate(dates) if i}
    br = {i: benchmark[d][1] / benchmark[dates[i - 1]][1] - 1 for i, d in enumerate(dates) if i}
    ur = {d: intel[d] / intel[us_dates[i - 1]] - 1 for i, d in enumerate(us_dates) if i}
    sr = {d: soxx[d] / soxx[us_dates[i - 1]] - 1 for i, d in enumerate(us_dates) if i}
    aligned, aligned_excess = {}, {}
    daily = []
    for i, d in enumerate(dates):
        if not i:
            continue
        # US close on the prior A-share calendar date occurs after that A close.
        observed = [u for u in ur if dates[i - 1] <= u < d]
        if not observed:
            continue
        aligned[i] = math.prod(1 + ur[u] for u in observed) - 1
        aligned_excess[i] = aligned[i] - (math.prod(1 + sr[u] for u in observed) - 1)
        daily.append({"a_date": d, "us_dates_available": ";".join(observed),
                      "intel_return": aligned[i], "intel_minus_soxx": aligned_excess[i],
                      "montage_return": ar[i], "montage_minus_588000": ar[i] - br[i]})

    correlations = []
    for period, low, high in [("all", START, END), ("2025", START, "2025-12-31"),
                              ("2026", "2026-01-01", END)]:
        for lag in [0, 1, 2, 3, 4, 5, 6, 7, 10]:
            indices = [i for i in aligned if i + lag < len(dates) and low <= dates[i + lag] <= high]
            correlations.append({"period": period, "additional_a_sessions": lag, "n": len(indices),
                                 "raw_correlation": correlation([aligned[i] for i in indices], [ar[i + lag] for i in indices]),
                                 "excess_correlation": correlation([aligned_excess[i] for i in indices], [ar[i + lag] - br[i + lag] for i in indices])})

    # Exploratory convention fixed here: +5% US day; take first event, skip
    # overlapping ten-A-session windows; require all horizons to be observable.
    events, last = [], -100
    for d in us_dates:
        if ur.get(d, 0) < 0.05:
            continue
        i = bisect.bisect_right(dates, d)
        if i >= len(dates) or i - last <= 10:
            continue
        last = i
        if i + 10 >= len(dates):
            continue
        assert d < dates[i]
        row = {"us_date": d, "intel_return": ur[d], "first_a_date": dates[i], "first_a_return": ar[i]}
        for horizon in [1, 3, 5, 10]:
            gain = a[dates[i + horizon]][1] / a[dates[i]][1] - 1
            market_gain = benchmark[dates[i + horizon]][1] / benchmark[dates[i]][1] - 1
            row[f"after_close_{horizon}d"] = gain
            row[f"excess_{horizon}d"] = gain - market_gain
        events.append(row)

    summary = {"cutoff_beijing": END, "a_rows": len(dates), "us_rows": len(us_dates),
               "event_rule": "INTC daily return >=5%; first nonoverlapping 10-A-session window; all horizons complete",
               "event_entry": "First subsequent A-share session close; illustrative, no fills/costs assumed",
               "limitations": ["Exploratory small sample, not a validated trading rule or probability forecast",
                               "588000 is a broad STAR-market proxy, not a pure memory-interface benchmark",
                               "Simple benchmark subtraction does not fully control factor betas",
                               "Unconditional overlapping windows are descriptive, not independent tests",
                               "Adjusted history is today's vendor snapshot, not a point-in-time archive"],
               "events": {}, "unconditional": {}}
    for horizon in [1, 3, 5, 10]:
        summary["events"][horizon] = describe([e[f"after_close_{horizon}d"] for e in events])
        summary["events"][horizon]["mean_excess_pp"] = stats.mean(e[f"excess_{horizon}d"] for e in events) * 100
    for horizon in [5, 10]:
        summary["unconditional"][horizon] = describe([a[dates[i + horizon]][1] / a[d][1] - 1 for i, d in enumerate(dates[:-horizon])])
    summary["latest"] = {"open": a[END][0], "close": a[END][1], "high": a[END][2], "low": a[END][3],
                          "ma20": stats.mean(a[d][1] for d in dates[-20:]),
                          "ma60": stats.mean(a[d][1] for d in dates[-60:]),
                          "daily_return_pct": ar[len(dates) - 1] * 100,
                          "five_session_return_pct": (a[END][1] / a[dates[-6]][1] - 1) * 100,
                          "volume_multiple_previous": a[END][4] / a[dates[-2]][4]}
    summary["correlations"] = correlations
    summary["april_wave"] = {}
    for name, prices in [("INTC", intel), ("688008", {d: v[1] for d, v in a.items()})]:
        window = {d: c for d, c in prices.items() if "2026-04-01" <= d <= "2026-07-10"}
        peak_date = max(window, key=window.get)
        summary["april_wave"][name] = {"peak_close_date": peak_date, "peak_adjusted_close": window[peak_date]}
    write_csv("aligned_daily_returns.csv", daily)
    write_csv("events.csv", events)
    (ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("correlations", "limitations")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

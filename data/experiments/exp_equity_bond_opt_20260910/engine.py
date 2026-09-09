"""Isolated policy adapter; production strategy/financing execution stays unchanged."""
import csv
from pathlib import Path
import sys
from policy import EXP, ROOT, ResearchConstraint, grid
sys.path.insert(0, str(ROOT/'scripts'))
import backtest_valuation_strategy as bt


def main():
    i = sys.argv.index('--eb-policy')
    arm = sys.argv[i+1]
    del sys.argv[i:i+2]
    spec = next(r for r in grid() if r['arm'] == arm)
    if arm not in ('BASE', 'OFF'):
        bt.EquityBondConstraint = lambda *a, **kw: ResearchConstraint(*a, **kw, spec=spec)
    tag = sys.argv[sys.argv.index('--label-suffix')+1].lstrip('_')
    if arm == 'OFF':
        sys.argv += ['--equity-bond-mode', 'off']
    original = bt.summarize
    def capture(name, result, capital, benchmark, risk_free):
        # All paths retain exact NAV for independent annual/window/date checks.
        if name.startswith('trend_'):
            path = EXP/'nav'/f'{tag}.csv'
            path.parent.mkdir(exist_ok=True)
            with path.open('w', newline='') as f:
                w = csv.writer(f, lineterminator='\n')
                w.writerow(('date','net_equity','cash','positions','debt','margin_ratio','top1_weight','top3_weight'))
                w.writerows(result['equity'])
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    return bt.main()


if __name__ == '__main__':
    raise SystemExit(main())

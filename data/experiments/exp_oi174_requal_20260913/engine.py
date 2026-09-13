"""Isolated policy adapter reusing the frozen research policy; production strategy/financing execution stays unchanged."""
import csv
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
PRIOR = EXP.parent / 'exp_equity_bond_opt_20260910'
sys.path.insert(0, str(PRIOR))
sys.path.insert(0, str(ROOT / 'scripts'))
from policy import ResearchConstraint, grid  # noqa: E402  frozen 2026-09-10 implementation
import backtest_valuation_strategy as bt  # noqa: E402


def main():
    if os.environ.get('RAYKEY_ACTIONS'):          # frozen research copies shared with exp_oi167_land_20260913
        bt.ACTIONS = Path(os.environ['RAYKEY_ACTIONS'])
    if os.environ.get('RAYKEY_RATES'):
        bt.RATES = Path(os.environ['RAYKEY_RATES'])
    i = sys.argv.index('--eb-policy')
    arm = sys.argv[i + 1]
    del sys.argv[i:i + 2]
    spec = next(r for r in grid() if r['arm'] == arm)
    if arm not in ('BASE', 'OFF'):
        bt.EquityBondConstraint = lambda *a, **kw: ResearchConstraint(*a, **kw, spec=spec)
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize

    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            path = EXP / 'nav' / f'{tag}.csv'
            path.parent.mkdir(exist_ok=True)
            with path.open('w', newline='') as f:
                w = csv.writer(f, lineterminator='\n')
                w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    return bt.main()


if __name__ == '__main__':
    raise SystemExit(main())

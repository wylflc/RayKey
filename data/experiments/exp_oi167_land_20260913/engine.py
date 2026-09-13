"""Native production engine; capture exact NAV and run stats without replacing trading or signal logic.
Env overrides (research copies only, never rewriting live inputs): RAYKEY_ACTIONS, RAYKEY_RATES, RAYKEY_GROUP."""
import csv
import json
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt


def main():
    if os.environ.get('RAYKEY_ACTIONS'):
        bt.ACTIONS = Path(os.environ['RAYKEY_ACTIONS'])
    if os.environ.get('RAYKEY_RATES'):
        bt.RATES = Path(os.environ['RAYKEY_RATES'])
    group = os.environ.get('RAYKEY_GROUP', 'default')
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    summarize = bt.summarize

    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            (EXP / 'nav' / group).mkdir(parents=True, exist_ok=True)
            with (EXP / 'nav' / group / f'{tag}.csv').open('w', newline='') as f:
                w = csv.writer(f, lineterminator='\n')
                w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
            (EXP / 'stats' / group).mkdir(parents=True, exist_ok=True)
            (EXP / 'stats' / group / f'{tag}.json').write_text(json.dumps(dict(result['stats']), ensure_ascii=False, indent=1) + '\n')
        return summarize(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    return bt.main()


if __name__ == '__main__':
    raise SystemExit(main())

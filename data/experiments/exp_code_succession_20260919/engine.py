"""Native engine wrapper: per-arm corporate-action file override (OI-192 OLD snapshot) + NAV/stats capture."""
import csv
import json
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt

if __name__ == '__main__':
    if os.environ.get('EXP_ACTIONS_FILE'):
        bt.ACTIONS = Path(os.environ['EXP_ACTIONS_FILE'])
        assert bt.ACTIONS.exists(), bt.ACTIONS
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize
    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            with (EXP / 'nav' / f'{tag}.csv').open('w', newline='') as f:
                w = csv.writer(f); w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
            (EXP / 'stats' / f'{tag}.json').write_text(json.dumps(result['stats'], ensure_ascii=False, indent=2) + '\n')
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    raise SystemExit(bt.main())

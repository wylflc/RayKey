"""Patched backtest engine for OI-237: the OI-236 patch (`../exp_oi236_20260929/patch.py`, stacked on OI-235 and OI-233) on the frozen
v4.221 corporate actions, no new switches. Captures NAV/stats for every path, closed cycles and the stretch-trim log (tlog/) for every
full-sample path, and the anchor-start contrib file for case attribution."""
import csv
import json
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'data/experiments/exp_oi236_20260929'))
from patch import load  # noqa: E402

if __name__ == '__main__':
    bt = load()
    bt.ACTIONS = Path(os.environ['EXP_ACTIONS_FILE'])
    assert bt.ACTIONS.exists(), bt.ACTIONS
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize

    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            if tag.endswith('full20111101'):
                bt.write_trades(EXP / f'contrib_{tag}_trades.csv', result['closed'], {})
            if 'full' in tag and 'ex5' not in tag:
                bt.write_trades(EXP / 'trades' / f'{tag}_trades.csv', result['closed'], {})
                (EXP / 'tlog' / f'{tag}.json').write_text(json.dumps(result['bb_log'], ensure_ascii=False) + '\n')
            with (EXP / 'nav' / f'{tag}.csv').open('w', newline='') as f:
                w = csv.writer(f); w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
            (EXP / 'stats' / f'{tag}.json').write_text(json.dumps(result['stats'], ensure_ascii=False, indent=2) + '\n')
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    raise SystemExit(bt.main())

"""Native production engine for both frozen OI-198 arms; capture NAV/stats."""
import csv
import json
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import corporate_actions as ca
ca.PRICE_TERMS_PATH = EXP/'old_inputs/data/reference/a_share_exright_terms.csv'
import backtest_valuation_strategy as bt
bt.OHLCV_DIR = EXP/'old_inputs/data/raw/ohlcv'
bt.RATES = EXP/'old_inputs/data/reference/cost_of_equity_inputs.csv'

if __name__ == '__main__':
    if os.environ.get('EXP_ACTIONS_FILE'):
        bt.ACTIONS = Path(os.environ['EXP_ACTIONS_FILE'])
        assert bt.ACTIONS.exists(), bt.ACTIONS
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize
    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            if tag in ('OLDfull20111101', 'NEWfull20111101'):
                bt.write_trades(EXP/f'contrib_{tag}_trades.csv', result['closed'], {})
            with (EXP / 'nav' / f'{tag}.csv').open('w', newline='') as f:
                w = csv.writer(f); w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
            (EXP / 'stats' / f'{tag}.json').write_text(json.dumps(result['stats'], ensure_ascii=False, indent=2) + '\n')
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    raise SystemExit(bt.main())

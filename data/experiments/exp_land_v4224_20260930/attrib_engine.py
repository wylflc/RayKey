"""生产回测引擎包一层：趋势臂结束时把闭合周期（含 contrib）写到 `--label-suffix` 对应的 trades/<tag>_cycles.csv（OI-230 engine.py 同法）。"""
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt  # noqa: E402

if __name__ == '__main__':
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize

    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            bt.write_trades(EXP / 'trades' / f'{tag}_cycles.csv', result['closed'], {})
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    raise SystemExit(bt.main())

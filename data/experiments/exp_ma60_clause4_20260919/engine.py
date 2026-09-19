"""Isolated slope-gate insertion into the candidate gate (exp_oi179 form); BASE executes the native engine.
Also dumps per-code relative contributions (result['contrib']) for winner-dose exclusion sets and clause-11 attribution."""
import csv
import inspect
import json
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from slope import SlopeGuard
import backtest_valuation_strategy as bt


def install(spec):
    if not spec['lag']:
        return
    source = inspect.getsource(bt.run)
    setup = '    stats = stats if stats is not None else collections.Counter()\n'
    marker = '        if vol_on_buy and eligible:\n'
    assert source.count(setup) == 1 and source.count(marker) == 1
    source = source.replace(setup, setup + '    _slope = _SlopeGuard(prices, mas, actions, _SLOPE_SPEC)\n', 1)
    insert = '''        if eligible:
            _slope_kept = []
            for r in eligible:
                if _slope.allows(r[0], buy_day):
                    _slope_kept.append(r)
                else:
                    _kind = '加仓' if r[0] in portfolio.lots else '建仓'
                    stats['MA斜率·' + _kind + '候选挡下'] += 1
            eligible = _slope_kept
'''
    source = source.replace(marker, insert + marker, 1)
    bt.__dict__.update(_SlopeGuard=SlopeGuard, _SLOPE_SPEC=spec)
    exec(compile(source, str(EXP / 'generated_candidate_gate.py'), 'exec'), bt.__dict__)


def main():
    i = sys.argv.index('--slope-arm'); arm = sys.argv[i + 1]; del sys.argv[i:i + 2]
    spec = next(r for r in json.loads((EXP / 'grid.json').read_text()) if r['arm'] == arm)
    install(spec)
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize
    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            with (EXP / 'nav' / f'{tag}.csv').open('w', newline='') as f:
                w = csv.writer(f, lineterminator='\n')
                w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
            (EXP / 'stats' / f'{tag}.json').write_text(json.dumps(dict(result['stats']), ensure_ascii=False, indent=2) + '\n')
            (EXP / 'contrib' / f'{tag}.json').write_text(json.dumps(dict(result.get('contrib') or {}), ensure_ascii=False) + '\n')
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    return bt.main()


if __name__ == '__main__':
    raise SystemExit(main())

"""Isolated research engine: signal-side P/V can release the position cap."""
import csv
import json
import os
import sys
import types
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))


def load_engine(patched=True, frozen=False):
    source_path = ROOT / 'scripts/backtest_valuation_strategy.py'
    source = source_path.read_text()
    def replace(old, new):
        nonlocal source
        assert source.count(old) == 1, (old, source.count(old))
        source = source.replace(old, new)
    if patched:
        replace('position_cap: float = 0.0, only_tiers:',
                'position_cap: float = 0.0, position_cap_pv_release: float = 0.0, only_tiers:')
        replace('    if equity_bond is not None and (exec_delay < 1',
                '    if not math.isfinite(position_cap_pv_release) or position_cap_pv_release < 0:\n'
                '        raise ValueError("P/V cap release must be finite and nonnegative")\n'
                '    def cap_on(pv):\n'
                '        return bool(position_cap) and not (position_cap_pv_release and math.isfinite(pv) and 0 < pv < position_cap_pv_release)\n'
                '    if equity_bond is not None and (exec_delay < 1')
        replace('if position_cap and r[0] in portfolio.lots', 'if cap_on(r[3]) and r[0] in portfolio.lots')
        replace('if position_cap and portfolio.lots[code].shares * close',
                'if cap_on(ratio) and portfolio.lots[code].shares * close')
        replace('if _l is not None and position_cap and _l.shares * r[1]',
                'if _l is not None and cap_on(r[3]) and _l.shares * r[1]')
        replace('            if position_cap:\n                held_value',
                '            cap_active = cap_on(ratio)\n'
                '            if position_cap and not cap_active:\n'
                '                stats["低PV豁免单票上限·可买机会"] += 1\n'
                '                if code in portfolio.lots and portfolio.lots[code].shares * close >= equity * position_cap:\n'
                '                    stats["低PV豁免单票上限·已超限机会"] += 1\n'
                '            if cap_active:\n                held_value')
        replace('if position_cap and bp * lot_size > room + 1e-8:',
                'if cap_active and bp * lot_size > room + 1e-8:')
        replace('    parser.add_argument("--only-tiers",',
                '    parser.add_argument("--position-cap-pv-release", type=float, default=0.0)\n'
                '    parser.add_argument("--only-tiers",')
        replace('                     + (f"_only{args.only_tiers}"',
                '                     + (f"_capfreepv{args.position_cap_pv_release:g}" if args.position_cap_pv_release else "")\n'
                '                     + (f"_only{args.only_tiers}"')
        replace('                         position_cap=args.position_cap,',
                '                         position_cap=args.position_cap, position_cap_pv_release=args.position_cap_pv_release,')
    module = types.ModuleType('pv_cap_research' if patched else 'pv_cap_control')
    module.__file__ = str(source_path)
    sys.modules[module.__name__] = module
    exec(compile(source, str(source_path), 'exec'), module.__dict__)
    if frozen:
        import corporate_actions as ca
        ca.PRICE_TERMS_PATH = EXP/'inputs/data/reference/a_share_exright_terms.csv'
        for attr, path in {'OHLCV_DIR':'data/raw/ohlcv',
                           'ACTIONS':'data/raw/corporate_actions/a_share_corporate_actions.csv',
                           'RATES':'data/reference/cost_of_equity_inputs.csv',
                           'BENCHMARK':'data/raw/ohlcv/INDEX_000300.csv',
                           'DELISTED_ROSTER':'data/raw/a_share_delisted_roster.csv',
                           'NAMES_PATH':'data/processed/a_share_watchlist_quality_tiers.csv'}.items():
            setattr(module, attr, EXP/'inputs'/path)
    return module


if __name__ == '__main__':
    bt = load_engine(patched=os.getenv('PV_CAP_NATIVE') != '1', frozen=True)
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize
    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            with (EXP/'nav'/f'{tag}.csv').open('w', newline='') as f:
                w=csv.writer(f)
                w.writerow(('date','net_equity','cash','positions','debt','margin_ratio','top1_weight','top3_weight'))
                w.writerows(result['equity'])
            (EXP/'stats'/f'{tag}.json').write_text(json.dumps(result['stats'],ensure_ascii=False,indent=2)+'\n')
        return original(name,result,capital,benchmark,risk_free)
    bt.summarize=capture
    raise SystemExit(bt.main())

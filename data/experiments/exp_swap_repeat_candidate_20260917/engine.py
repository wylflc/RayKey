"""Research-only iteration change; the native engine and production BASE stay intact."""
import csv
import hashlib
import inspect
import json
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt

NATIVE_RUN = bt.run
NATIVE_SOURCE = inspect.getsource(NATIVE_RUN)
LOOP = 'for code, close, value, ratio in (eligible[:max_positions] if swap_mode == "legacy" else []):'
REPEAT_LOOP = ('for code, close, value, ratio in _repeat_swap_candidates('
               '(eligible[:max_positions] if swap_mode == "legacy" else []), lambda: sell_count):')
TRACE_POINT = '                swap_target_pv[code] = ratio\n'
TRACE_CALL = (TRACE_POINT + '                _record_swap(sig_day, day, code, worst, sold_qty, sp, '
              'cand_ratio, (hold_exec_today if t1_swap else hold_today).get(worst, (None, None, None))[2], '
              'funds, funds_available(), budget, sell_budget, bool(swap_tag))\n')
TRACE_FIELDS = ('signal_date', 'exec_date', 'target', 'source', 'shares', 'price',
                'candidate_pv', 'source_pv', 'funds_before', 'funds_after', 'buy_tranche',
                'sell_tranche', 'gain_source')


def repeat_candidates(candidates, progress):
    """Retry a candidate only after an actual sale; no-progress exits remain finite."""
    for candidate in candidates:
        while True:
            before = progress()
            yield candidate
            if progress() <= before:
                break


def install(repeat=False, recorder=None):
    assert NATIVE_SOURCE.count(LOOP) == 1
    assert NATIVE_SOURCE.count(TRACE_POINT) == 1
    source = NATIVE_SOURCE.replace(TRACE_POINT, TRACE_CALL)
    if repeat:
        source = source.replace(LOOP, REPEAT_LOOP)
    bt.__dict__['_repeat_swap_candidates'] = repeat_candidates
    bt.__dict__['_record_swap'] = recorder or (lambda *args: None)
    exec(compile(source, str(EXP / 'engine.py') + ':run', 'exec'), bt.__dict__)
    return hashlib.sha256(source.encode()).hexdigest()


def main():
    repeat = '--repeat-swap-candidate' in sys.argv
    if repeat:
        sys.argv.remove('--repeat-swap-candidate')
        assert '--swap-gain-once' in sys.argv and '--swap-partial' in sys.argv
        assert sys.argv[sys.argv.index('--swap-repeat') + 1] == 'skip'
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    for name in ('nav', 'stats', 'swaps'):
        (EXP / name).mkdir(exist_ok=True)
    original_summary = bt.summarize
    with (EXP / 'swaps' / f'{tag}.csv').open('w', newline='') as handle:
        writer = csv.writer(handle, lineterminator='\n')
        writer.writerow(TRACE_FIELDS)
        source_hash = install(repeat, lambda *args: writer.writerow(args))

        def capture(name, result, capital, benchmark, risk_free):
            if name.startswith('trend_'):
                with (EXP / 'nav' / f'{tag}.csv').open('w', newline='') as f:
                    w = csv.writer(f, lineterminator='\n')
                    w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt',
                                'margin_ratio', 'top1_weight', 'top3_weight'))
                    w.writerows(result['equity'])
                value = dict(stats=result['stats'], repeat=repeat, patched_run_sha256=source_hash,
                             fees=result['fees'], interest_paid=result['interest_paid'],
                             dividend_tax_paid=result['dividend_tax_paid'], final_debt=result['final_debt'],
                             contributions=result['contrib'])
                (EXP / 'stats' / f'{tag}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            return original_summary(name, result, capital, benchmark, risk_free)

        bt.summarize = capture
        return bt.main()


if __name__ == '__main__':
    raise SystemExit(main())

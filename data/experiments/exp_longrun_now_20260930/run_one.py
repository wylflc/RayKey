"""一条长跑路径：原生引擎、重建状态与续期行情，落盘末日持仓、逐周期、流水、逐日持仓与净值。

    python3 run_one.py S15 2011-11-01      # S15 = 现行 BASE（v4.222）；OLD = 去掉 v4.222 三个开关（v4.221 BASE）
"""
import csv
import gzip
import json
import shlex
import sys

from common import EXP, OHLCV, PANEL_STATES, S15_FLAGS
import backtest_valuation_strategy as bt
import sweep_backtest_configs as sw

LOT_FIELDS = ('code', 'entry_date', 'exit_date', 'exit_reason', 'buys', 'sells', 'invested', 'proceeds', 'dividends',
              'max_drawdown', 'max_money_drawdown', 'contrib', 'entry_ratio', 'entry_value')


def main(arm: str, start: str) -> None:
    assert sw.BASE.count(S15_FLAGS) == 1, 'BASE 不含 v4.222 三个开关'
    base = sw.BASE if arm == 'S15' else sw.BASE.replace(S15_FLAGS, '')
    out = EXP / 'runs' / f'{arm}_{start}'
    for sub in ('', 'cache', 'daily'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    bt.OHLCV_DIR = OHLCV
    calls = []
    original = bt.run

    def wrapped(*a, **k):
        snaps, ledger = [], []
        k['portfolio_snapshots'], k['ledger'] = snaps, ledger
        result = original(*a, **k)
        calls.append((a[0] if a else k.get('strategy'), snaps, ledger, result))
        return result
    bt.run = wrapped
    sys.argv = ['backtest_valuation_strategy.py', *shlex.split(base), '--since', start, '--label-suffix', f'_{arm}{start}',
                '--out-dir', str(out / 'cache'), '--equity-bond-log-dir', str(out / 'daily'),
                '--daily-states', str(PANEL_STATES / 'a_share_daily_states_adopted.csv'),
                '--hold-states', str(PANEL_STATES / 'a_share_daily_states_hold.csv')]
    try:
        bt.main()
    except SystemExit as exc:
        assert not exc.code, exc.code
    trend = [c for c in calls if c[0] == 'trend']
    assert len(trend) == 1, [c[0] for c in calls]
    _, snaps, ledger, result = trend[0]
    last = snaps[-1]
    equity = {d: e for d, e, *_ in result['equity']}
    json_out = dict(arm=arm, start=start, date=last['date'], cash=last['cash'], debt=last['debt'],
                    equity=equity[last['date']], holdings=last['holdings'])
    (out / 'final.json').write_text(json.dumps(json_out, ensure_ascii=False, default=float, indent=1) + '\n')
    with (out / 'equity.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'equity', 'cash', 'n', 'debt', 'margin_ratio', 'top1', 'top3'])
        for row in result['equity']:
            w.writerow(list(row) + [''] * (8 - len(row)))
    with (out / 'cycles.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(LOT_FIELDS)
        for lot in result['closed']:
            w.writerow([getattr(lot, k) for k in LOT_FIELDS])
    if ledger:
        with (out / 'ledger.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(ledger[0]))
            w.writeheader()
            w.writerows(ledger)
    with gzip.open(out / 'holdings_daily.csv.gz', 'wt', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'code', 'shares', 'cost', 'equity', 'debt'])
        for s in snaps:
            for c, h in s['holdings'].items():
                w.writerow([s['date'], c, f"{h['shares']:.0f}", f"{h['cost']:.6f}", f"{equity.get(s['date'], 0):.2f}",
                            f"{s['debt']:.2f}"])
    print(arm, start, last['date'], len(last['holdings']), f"{equity[last['date']]:.0f}", flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])

"""OI-241 回测引擎：原生引擎（v4.222）加本目录 patch.py（`--add-bt` 与逐 (代码, 年) contrib 记账），公司行动冻结在 v4.221
（同 OI-237／OI-240）。每条路径留净值与统计；全样本路径另留闭合周期（trades/）与逐年 contrib（detail/）。"""
import csv
import json
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))
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
                (EXP / 'detail' / f'{tag}.json').write_text(json.dumps(dict(final_equity=result['equity'][-1][1],
                                                                            contrib_year=result['contrib_year']), ensure_ascii=False) + '\n')
            with (EXP / 'nav' / f'{tag}.csv').open('w', newline='') as f:
                w = csv.writer(f); w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
            (EXP / 'stats' / f'{tag}.json').write_text(json.dumps(result['stats'], ensure_ascii=False, indent=2) + '\n')
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    raise SystemExit(bt.main())

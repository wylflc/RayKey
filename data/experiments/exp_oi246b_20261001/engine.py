"""OI-246 第二段回测引擎：原生引擎加本目录 patch.py，正式公司行动（同 v4.225 在册 BASE）。
每条路径留净值与统计；全样本路径另留闭合周期（trades/）与挡下记录（blocks/：信号日, 代码）。"""
import csv
import json
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))
from patch import load  # noqa: E402

if __name__ == '__main__':
    bt = load()
    tag = sys.argv[sys.argv.index('--label-suffix') + 1].lstrip('_')
    full = 'full' in tag and 'ex5' not in tag
    original_run = bt.run

    def run(*a, **k):
        bt.TA_LOG.clear()
        return original_run(*a, **k)
    bt.run = run
    original = bt.summarize

    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            if tag.endswith('full20111101'):
                bt.write_trades(EXP / f'contrib_{tag}_trades.csv', result['closed'], {})
            if full:
                bt.write_trades(EXP / 'trades' / f'{tag}_trades.csv', result['closed'], {})
                with (EXP / 'blocks' / f'{tag}.csv').open('w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(('signal_day', 'code'))
                    w.writerows(bt.TA_LOG)
            with (EXP / 'nav' / f'{tag}.csv').open('w', newline='') as f:
                w = csv.writer(f)
                w.writerow(('date', 'net_equity', 'cash', 'positions', 'debt', 'margin_ratio', 'top1_weight', 'top3_weight'))
                w.writerows(result['equity'])
            (EXP / 'stats' / f'{tag}.json').write_text(json.dumps(result['stats'], ensure_ascii=False, indent=2) + '\n')
        return original(name, result, capital, benchmark, risk_free)
    bt.summarize = capture
    raise SystemExit(bt.main())

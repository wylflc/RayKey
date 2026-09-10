"""Native production engine; capture exact NAV without replacing trading or signal logic."""
import csv
from pathlib import Path
import sys
EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import backtest_valuation_strategy as bt


def main():
    tag=sys.argv[sys.argv.index('--label-suffix')+1].lstrip('_')
    summarize=bt.summarize
    def capture(name,result,capital,benchmark,risk_free):
        if name.startswith('trend_'):
            (EXP/'nav').mkdir(exist_ok=True)
            with (EXP/'nav'/f'{tag}.csv').open('w',newline='') as f:
                w=csv.writer(f,lineterminator='\n')
                w.writerow(('date','net_equity','cash','positions','debt','margin_ratio','top1_weight','top3_weight'))
                w.writerows(result['equity'])
        return summarize(name,result,capital,benchmark,risk_free)
    bt.summarize=capture
    return bt.main()


if __name__=='__main__':raise SystemExit(main())

"""OI-246 第二段：由现行候选侧状态与估值带生成逐票谷底守卫权重分段。

输出 `trough_v.csv`（代码, 起始日, v）：状态行所挂带（报告期, 可得日）在 `roic_bands.csv` 的 `trough_weight`，
只在 v 变化时记一行；匹配不到的记 0。

    python3 prep.py
"""
import csv
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
BANDS = ROOT / 'data/processed/roic_bands.csv'
OUT = EXP / 'trough_v.csv'


def main():
    tw = {}
    with BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            v = float(r['trough_weight'] or 0)
            if v > 0:
                tw[(r['security_code'], r['report_date'], r['available_at'])] = v
    runs, last, last_day, rows = [], {}, {}, 0
    with STATES.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        h = next(reader)
        ic, idt, irp, iav = (h.index(k) for k in ('security_code', 'date', 'band_report_date', 'band_available_at'))
        for row in reader:
            rows += 1
            code, d = row[ic], row[idt]
            assert d > last_day.get(code, ''), ('状态行须按代码内日期递增', code, d)
            last_day[code] = d
            v = tw.get((code, row[irp], row[iav]), 0.0)
            if last.get(code) != v:
                runs.append((code, d, f'{v:.3f}'))
                last[code] = v
    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['security_code', 'from', 'v'])
        w.writerows(runs)
    print(f'{rows} 状态行，{len(runs)} 段，其中 v > 0 的 {sum(1 for r in runs if float(r[2]) > 0)} 段')


if __name__ == '__main__':
    main()

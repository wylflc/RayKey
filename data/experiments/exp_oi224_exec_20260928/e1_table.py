"""OI-224：E1（近三个财年经营现金流合计 ÷ 归母净利合计）的时点表，供回测引擎的「E1 最差一档不放宽」变体读取。

每只有三大报表的公司、每个年报一行：`security_code, report_date, available_at, e1`。可得日取三年中最晚一份年报的可得日
（`roic_inputs` 已按 §6.3 第 2 条封顶并处理重述版本）；三年不齐或净利合计 ≤ 0 时 e1 留空。口径与
`../exp_oi224_traps_20260928/traps.py` 的 E1 相同（该处按观测日取最近三年，此处按年报逐行展开，引擎按日取最近一行）。

    python3 e1_table.py        # → e1_table.csv
"""
import csv
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import roic_inputs  # noqa: E402


def main():
    codes = {p.stem for p in (ROOT / 'data/raw/ohlcv').glob('*.csv') if not p.stem.startswith('INDEX')}
    years = roic_inputs.load_statements(codes, roic_inputs.STMT_DIR, ic_floor=0.1, caliber='nonop', notice_cap=True,
                                        restricted_cash='notes_wc')
    rows = []
    for code, by_period in sorted(years.items()):
        notices = sorted({y.notice_date for y in by_period.values() if y.notice_date})
        for day in notices:
            ys = sorted(roic_inputs.years_before(by_period, day, 3), key=lambda y: y.period)
            if not ys:
                continue
            cfo = [y.cfo for y in ys if y.cfo is not None]
            npf = [y.parent_netprofit for y in ys if y.parent_netprofit is not None]
            ok = len(ys) == 3 and len(cfo) == 3 and len(npf) == 3 and sum(npf) > 0
            rows.append(dict(security_code=code, report_date=ys[-1].period, available_at=day,
                             e1=f'{sum(cfo) / sum(npf):.6f}' if ok else ''))
    with (EXP / 'e1_table.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['security_code', 'report_date', 'available_at', 'e1'])
        w.writeheader(); w.writerows(rows)
    print('rows', len(rows), 'codes', len({r['security_code'] for r in rows}), 'with e1', sum(1 for r in rows if r['e1']))


if __name__ == '__main__':
    main()

"""OI-205 机制层核对：峰／谷守卫触发的年报年份，守卫锚与不设守卫的锚，谁更接近其后实际的 NOPAT ÷ 账面？

不看回测收益。按 §6.5.1 用年报重算（比率 = NOPAT ÷ 母公司权益，经营账面的外生权益调整忽略；年报行 TTM 因子 = 1）：
  十年中位（含当年，≥4 年）、五年中位、三年中位、λ = 近两次变动上行数 ÷ 2、当期 = 当年比率；
  峰权重 w = clip((当期/十年中位 − 1.3)/0.6)，谷权重 v = clip((十年中位/当期 − 1.3)/0.6)；
  无守卫锚 = 三年中位 + λ(当期 − 三年中位)；守卫锚 = (1 − max(w,v))·无守卫锚 + max(w,v)·五年中位。
实际 = 其后 3 年／5 年比率均值（须完整）。误差 = ln(锚 ÷ 实际)，比较 |误差| 中位与偏差中位，按策略标签分组（现行标签，有后见）。
    python3 mechanism.py [--all-market]
"""
import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import roic_inputs  # noqa: E402

K_EDGE, RAMP2 = 1.3, 0.6
GROUPS = {'H': 'cyclical', 'F': 'cyclical'}


def clip(x: float) -> float:
    return min(1.0, max(0.0, x))


def rows_for(code: str, years: dict) -> list[dict]:
    ser = sorted((int(p[:4]), y.nopat / y.parent_equity) for p, y in years.items()
                 if p.endswith('-12-31') and y.nopat is not None and y.parent_equity and y.parent_equity > 0)
    ratio = dict(ser)
    level = {int(p[:4]): (y.nopat, y.parent_equity) for p, y in years.items()
             if p.endswith('-12-31') and y.nopat is not None and y.parent_equity and y.parent_equity > 0}
    out = []
    for yr, cur in ser:
        hist = [ratio[y] for y in range(yr - 9, yr + 1) if y in ratio]
        five = [ratio[y] for y in range(yr - 4, yr + 1) if y in ratio]
        if len(hist) < 4 or len(five) < 3 or cur <= 0:
            continue
        med10, med5, base3 = statistics.median(hist), statistics.median(five), statistics.median(five[-3:])
        if med10 <= 0:
            continue
        lam = sum(1 for i in (-1, -2) if five[i] > five[i - 1]) / 2
        s = cur / med10
        w, v = clip((s - K_EDGE) / RAMP2), clip((1 / s - K_EDGE) / RAMP2)
        if max(w, v) <= 0:
            continue
        noncyc = base3 + lam * (cur - base3)
        guarded = (1 - max(w, v)) * noncyc + max(w, v) * med5
        rec = dict(code=code, year=yr, side='peak' if w > 0 else 'trough', weight=max(w, v), cur=cur, med5=med5,
                   noncyc=noncyc, guarded=guarded)
        for h in (3, 5):
            fwd = [ratio.get(yr + i) for i in range(1, h + 1)]
            rec[f'real{h}'] = statistics.mean(fwd) if all(f is not None for f in fwd) else None
            lv = [level.get(yr + i) for i in range(1, h + 1)]      # 第二口径：其后 NOPAT 均值 ÷ 当年账面
            rec[f'level{h}'] = (statistics.mean(x[0] for x in lv) / level[yr][1]) if all(lv) else None
        out.append(rec)
    return out


def err(anchor: float, real: float | None) -> float | None:
    if real is None or real <= 0 or anchor <= 0:
        return None
    return math.log(anchor / real)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--all-market', action='store_true')
    ap.add_argument('--realized', choices=['real', 'level'], default='real', help='real = 其后比率均值；level = 其后 NOPAT 均值 ÷ 当年账面')
    args = ap.parse_args()
    tags = {r['security_code']: r['strategy_tag_letter'] for r in csv.DictReader((ROOT / 'data/interim/strategy_tag_map.csv').open(encoding='utf-8-sig'))}
    codes = None if args.all_market else set(tags)
    stmts = roic_inputs.load_statements(codes, roic_inputs.STMT_DIR, ic_floor=0.1, caliber='nonop', notice_cap=True)
    recs = []
    for code, years in stmts.items():
        if any(y.is_financial for y in years.values()):
            continue
        for r in rows_for(code, years):
            r['tag'] = tags.get(code, '')
            r['group'] = GROUPS.get(r['tag'], 'untagged' if not r['tag'] else 'other')
            recs.append(r)
    summary = {}
    for h in (3, 5):
        cells = defaultdict(list)
        for r in recs:
            eg, eu = err(r['guarded'], r[f'{args.realized}{h}']), err(r['noncyc'], r[f'{args.realized}{h}'])
            if eg is None or eu is None:
                continue
            for key in ((r['group'], r['side']), (r['group'], 'all'), ('ALL', r['side'])):
                cells[key].append((eg, eu, r['weight']))
        for key, vals in sorted(cells.items()):
            full = [x for x in vals if x[2] >= 1.0]
            summary[f'h{h}|{key[0]}|{key[1]}'] = dict(
                n=len(vals), n_full_weight=len(full),
                abs_err_guarded=statistics.median(abs(x[0]) for x in vals),
                abs_err_unguarded=statistics.median(abs(x[1]) for x in vals),
                bias_guarded=statistics.median(x[0] for x in vals),
                bias_unguarded=statistics.median(x[1] for x in vals),
                guard_closer_share=sum(1 for x in vals if abs(x[0]) < abs(x[1])) / len(vals))
    name = ('mechanism_all' if args.all_market else 'mechanism_tagged') + ('' if args.realized == 'real' else '_level') + '.json'
    (EXP / name).write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    with (EXP / name.replace('.json', '_rows.csv')).open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(recs[0].keys())); w.writeheader(); w.writerows(recs)
    print(f"{'窗':3} {'组':9} {'侧':6} {'n':>5} {'|误差|守卫':>9} {'|误差|无守卫':>10} {'偏差守卫':>8} {'偏差无守卫':>9} {'守卫更近':>7}")
    for k, s in summary.items():
        h, g, side = k.split('|')
        print(f"{h:3} {g:9} {side:6} {s['n']:>5} {s['abs_err_guarded']:>9.3f} {s['abs_err_unguarded']:>10.3f} "
              f"{s['bias_guarded']:>+8.3f} {s['bias_unguarded']:>+9.3f} {s['guard_closer_share']:>7.0%}")


if __name__ == '__main__':
    main()

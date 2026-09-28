#!/usr/bin/env python3
"""§12.1 第 11 款案例归因：两臂同一起点的闭合周期，按代码汇总 `contrib` 差，正负两个方向各取贡献最大的 N 只逐只列出。

每只列两臂的建仓与清仓日期、信号日 `P/V`（trades 的 `entry_pv_ratio`）、持有期内与其后 3 年模型价值 V 的变化
（V = 收盘 ÷ `valuation_ratio`，按送转折到建仓日股本）、建仓月其后 3 年含分红年化（答案卷 `f3`），并机械归类：
按建仓月答案卷标签分组求两臂 `contrib` 差，取与该股总差同号、绝对值最大的一组——机会组记「捕捉便宜机会」（候选多赚）
或「错过便宜机会」（候选少赚），陷阱组记「避开便宜陷阱」或「踩中便宜陷阱」，其余（一般、估值扩张、无标签、未满 3 年）
记「与估值无关」。归类只是读数的机械摘要，依据列在表内，由用户复核。前三只贡献占比见 `delta_attribution.py`。

    python3 scripts/experimental/case_attribution.py \\
        --base CONTROL=<对照 trades.csv> --arm G=<候选 trades.csv> \\
        --base-states <对照逐日状态> --arm-states <候选逐日状态> --out <报告.md>
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
from opportunity_trap_labels import OPP, TRAP  # noqa: E402

LABELS = ROOT / 'data/backtest/opportunity_trap_labels_v1.csv'
CLASSES = {(OPP, 1): '捕捉便宜机会', (OPP, -1): '错过便宜机会', (TRAP, 1): '避开便宜陷阱', (TRAP, -1): '踩中便宜陷阱'}


def load_trades(path: Path) -> dict[str, list[dict]]:
    out = defaultdict(list)
    with path.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            out[r['security_code'].zfill(6)].append(dict(
                entry=r['entry_date'], exit=r['exit_date'], pv=float(r['entry_pv_ratio'] or 'nan'),
                contrib=float(r['contrib'] or 0), ret=float(r['return_pct']) if r['return_pct'] else None,
                reason=r.get('exit_reason', '')))
    return out


def load_states(path: Path, codes: set[str]) -> dict[str, list[tuple[str, float, float]]]:
    """代码 → [(日期, 收盘, P/V)]，只留有效 P/V 的行。"""
    out = defaultdict(list)
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        head = next(reader)
        ic, idt, icl, ipv = (head.index(k) for k in ('security_code', 'date', 'close', 'valuation_ratio'))
        for row in reader:
            if row[ic] in codes and row[ipv]:
                try:
                    pv, close = float(row[ipv]), float(row[icl])
                except ValueError:
                    continue
                if pv > 0 and close > 0:
                    out[row[ic]].append((row[idt], close, pv))
    for rows in out.values():
        rows.sort()
    return out


def split_factor(actions: list[dict], a: str, b: str) -> float:
    """(a, b] 内送转的股数倍数（配股不计）。"""
    f = 1.0
    for x in actions:
        day = x.get('ex_dividend_date') or ''
        if a < day <= b:
            f *= 1 + (bhv._num(x.get('share_ratio')) or 0.0)
    return f


def value_at(rows, day: str):
    """≤ day 的最后一个状态行的 (日期, V, P/V)。"""
    i = bisect.bisect_right([r[0] for r in rows], day) - 1
    if i < 0:
        return None
    d, close, pv = rows[i]
    return d, close / pv, pv


def plus_years(day: str, years: int) -> str:
    d = date.fromisoformat(day)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:
        return d.replace(year=d.year + years, day=28).isoformat()


def describe(cycles, states, actions, labels, last_nav, last_month):
    out = []
    for c in cycles:
        month = c['entry'][:7]
        lab = labels.get(month)
        v0, vx, v3 = value_at(states, c['entry']), value_at(states, c['exit'] or last_nav), None
        target = plus_years(c['entry'], 3)
        if target <= last_nav:
            v3 = value_at(states, target)
        chg = lambda v: (None if v is None or v0 is None else v[1] * split_factor(actions, v0[0], v[0]) / v0[1] - 1)
        out.append(dict(entry=c['entry'], exit=c['exit'], exit_reason=c['reason'], entry_pv=c['pv'], contrib=c['contrib'],
                        ret=c['ret'], label=(lab or {}).get('label') or ('未满3年' if month > last_month else '无标签'),
                        f3=(lab or {}).get('f3'), dV_hold=chg(vx), dV_3y=chg(v3), pv_3y=v3[2] if v3 else None))
    return out


def classify(delta: float, by_label: dict) -> tuple[str, str]:
    sign = 1 if delta > 0 else -1
    same = {k: v for k, v in by_label.items() if v * sign > 0}
    if not same:
        return '与估值无关', '无同号标签组'
    top = max(same, key=lambda k: abs(same[k]))
    return CLASSES.get((top, sign), '与估值无关'), f'{top}组 Δ{same[top] * 100:+.2f}pp'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--base', required=True, help='标签=对照臂 trades.csv（同一起点）')
    ap.add_argument('--arm', required=True, help='标签=候选臂 trades.csv（同一起点）')
    ap.add_argument('--base-states', type=Path, required=True)
    ap.add_argument('--arm-states', type=Path, required=True)
    ap.add_argument('--labels', type=Path, default=LABELS)
    ap.add_argument('--actions', type=Path, help='除权事件表（缺省取 build_historical_valuation_bands.ACTIONS）')
    ap.add_argument('--last-nav', default='2026-08-28', help='回测末次净值日：其后 3 年不足的读数留空')
    ap.add_argument('--top', type=int, default=5)
    ap.add_argument('--out', type=Path, required=True, help='报告 .md；同名 .json 存全部读数')
    args = ap.parse_args()
    (bl, bp), (al, ap_) = (x.partition('=')[::2] for x in (args.base, args.arm))
    base, arm = load_trades(Path(bp)), load_trades(Path(ap_))
    delta = {c: sum(t['contrib'] for t in arm.get(c, [])) - sum(t['contrib'] for t in base.get(c, [])) for c in base.keys() | arm.keys()}
    ranked = sorted(delta, key=delta.get)
    picks = [c for c in ranked[::-1][:args.top] if delta[c] > 0] + [c for c in ranked[:args.top] if delta[c] < 0]
    labels, last_month = defaultdict(dict), ''
    with args.labels.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            last_month = max(last_month, r['month'])
            if r['code'] in picks:
                labels[r['code']][r['month']] = dict(label=r['label'] or '无标签', f3=float(r['f3']) if r['f3'] else None)
    if args.actions:
        bhv.ACTIONS = args.actions
    actions = bhv.load_actions()
    states = {bl: load_states(args.base_states, set(picks)), al: load_states(args.arm_states, set(picks))}
    names = {}
    with (ROOT / 'data/raw/a_share_securities.csv').open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            names[r['security_code'].zfill(6)] = r['security_name']
    result = dict(base=bl, arm=al, total_delta=sum(delta.values()), stocks=[])
    for code in picks:
        entry = dict(code=code, name=names.get(code, ''), delta=delta[code], cycles={})
        by_label = defaultdict(float)
        for lab, trades, sign in ((bl, base, -1), (al, arm, 1)):
            cyc = describe(trades.get(code, []), states[lab].get(code, []), actions.get(code, []), labels[code], args.last_nav, last_month)
            entry['cycles'][lab] = cyc
            for c in cyc:
                by_label[c['label']] += sign * c['contrib']
        entry['delta_by_label'] = dict(by_label)
        entry['class'], entry['basis'] = classify(delta[code], by_label)
        result['stocks'].append(entry)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n')
    args.out.write_text(render(result), encoding='utf-8')
    print(args.out)
    return 0


def render(res: dict) -> str:
    f = lambda x, d=2: '—' if x is None or x != x else f'{x:.{d}f}'
    p = lambda x: '—' if x is None or x != x else f'{x * 100:+.1f}%'
    out = [f"# 案例归因（§12.1 第 11 款）：{res['arm']} 对 {res['base']}", '',
           f"全部代码 contrib 差合计 {res['total_delta'] * 100:+.2f}pp（盈亏 ÷ 前一日净资产，同一起点）。归类为机械摘要，依据见各行。", '',
           '| 公司 | Δ | 归类 | 依据 |', '| --- | ---: | --- | --- |']
    out += [f"| {s['name']}（{s['code']}） | {s['delta'] * 100:+.2f}pp | {s['class']} | {s['basis']} |" for s in res['stocks']]
    for s in res['stocks']:
        out += ['', f"## {s['name']}（{s['code']}）Δ {s['delta'] * 100:+.2f}pp · {s['class']}", '',
                '| 臂 | 建仓 | 清仓 | 清仓原因 | 信号日 P/V | 建仓月标签 | 其后3年年化 | 持有期 V 变化 | 其后3年 V 变化 | 3年后 P/V | contrib |',
                '| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
        for lab, cyc in s['cycles'].items():
            out += [f"| {lab} | {c['entry']} | {c['exit'] or '持有'} | {c['exit_reason'] or ''} | {f(c['entry_pv'])} | {c['label']} | {p(c['f3'])} | "
                    f"{p(c['dV_hold'])} | {p(c['dV_3y'])} | {f(c['pv_3y'])} | {c['contrib'] * 100:+.2f}pp |" for c in cyc]
        out.append('')
        out.append('按建仓月标签的 contrib 差：' + '、'.join(f'{k} {v * 100:+.2f}pp' for k, v in sorted(s['delta_by_label'].items())))
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    raise SystemExit(main())

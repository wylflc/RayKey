#!/usr/bin/env python3
"""§12.1 第 13 款机会／陷阱读数（OI-222）：同一答案卷上，逐个口径报买入区对优秀便宜机会与便宜陷阱的覆盖。

估值层（每个 `--states` 口径，按各自买入线 `valuation_ratio ≤ 线` 判进买入区；无 `P/V` 记无法估值）：
  机会捕捉率（月、段）、买入区机会占比与相对基准率、买入区陷阱占比与相对基准率、陷阱踩中率（月、段）、无法估值占比；
  按股票整簇自助 5%～95% 区间，逐年列示；多个口径时第一个为对照，其余口径的差值用同一组重抽配对。
具名案例（`data/reference/opportunity_trap_cases.csv`）：区间内在册月份进买入区的占比、首次进入月、最低 `P/V`、无法估值月数。
策略层（给 `--trades` 时，每个口径一组 `*_trades.csv`，一个文件一个起点）：闭合周期按建仓月标签分组的笔数、投入占比与
  `contrib` 合计（跨起点中位）；具名案例区间内有持仓的起点数与 `contrib` 中位。

    python3 scripts/experimental/opportunity_trap_audit.py \\
        --states BASE=data/processed/a_share_daily_states_adopted.csv \\
        --trades 'BASE=data/experiments/exp_oi222_20260925/first_reading/bt/*/*_trades.csv' \\
        --out data/experiments/exp_oi222_20260925/first_reading/report.md
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
from opportunity_trap_labels import OPP, TRAP, episodes  # noqa: E402

LABELS = ROOT / 'data/backtest/opportunity_trap_labels_v1.csv'
CASES = ROOT / 'data/reference/opportunity_trap_cases.csv'
BOOT = 1000
SEED = 20260925
METRICS = (  # 键, 名称, 分子, 分母
    ('zone_share', '买入区占比', 'zone', 'n'),
    ('opp_capture_m', '机会捕捉率（月）', 'opp_zone', 'opp'),
    ('opp_capture_e', '机会捕捉率（段）', 'opp_ep_hit', 'opp_ep'),
    ('zone_opp_share', '买入区机会占比', 'opp_zone', 'zone'),
    ('zone_trap_share', '买入区陷阱占比', 'trap_zone', 'zone'),
    ('trap_hit_m', '陷阱踩中率（月）', 'trap_zone', 'trap'),
    ('trap_hit_e', '陷阱踩中率（段）', 'trap_ep_hit', 'trap_ep'),
    ('opp_nopv', '机会月无法估值', 'opp_nopv', 'opp'),
    ('trap_nopv', '陷阱月无法估值', 'trap_nopv', 'trap'),
)


def load_answer_key(path: Path):
    rows = []
    with path.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['panel'] == 'True' and r['label']:
                r['panel'] = True
                rows.append(r)
    eps = episodes(rows)
    for i, ep in enumerate(eps):
        for r in ep:
            r['episode'] = i
    return rows, eps


def load_pv(path: Path, keys: set) -> dict:
    """(代码, 日期) → P/V；有状态行但无有效 `valuation_ratio` 记 None，没有状态行的键不出现。"""
    out = {}
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        head = next(reader)
        ic, idt, ipv = head.index('security_code'), head.index('date'), head.index('valuation_ratio')
        for row in reader:
            key = (row[ic], row[idt])
            if key in keys:
                try:
                    v = float(row[ipv])
                except ValueError:
                    v = None
                out[key] = v if v is not None and v > 0 else None
    return out


def counts(rows, pv: dict, line: float, n_eps: int):
    """逐股票累计各分子分母（整簇自助的单位是股票）。"""
    stocks = sorted({r['code'] for r in rows})
    idx = {c: i for i, c in enumerate(stocks)}
    names = ('n', 'zone', 'opp', 'trap', 'opp_zone', 'trap_zone', 'opp_nopv', 'trap_nopv', 'opp_ep', 'opp_ep_hit', 'trap_ep', 'trap_ep_hit')
    c = {k: np.zeros(len(stocks)) for k in names}
    ep_hit = np.zeros(n_eps, bool)
    ep_stock, ep_kind = np.zeros(n_eps, int), [''] * n_eps
    for r in rows:
        s = idx[r['code']]
        v = pv.get((r['code'], r['date']))
        zone = v is not None and v <= line
        opp, trap = r['label'] == OPP, r['label'] == TRAP
        c['n'][s] += 1
        c['zone'][s] += zone
        c['opp'][s] += opp
        c['trap'][s] += trap
        c['opp_zone'][s] += opp and zone
        c['trap_zone'][s] += trap and zone
        c['opp_nopv'][s] += opp and v is None
        c['trap_nopv'][s] += trap and v is None
        if 'episode' in r:
            e = r['episode']
            ep_hit[e] |= zone
            ep_stock[e], ep_kind[e] = s, r['label']
    for e in range(n_eps):
        key = 'opp' if ep_kind[e] == OPP else 'trap'
        c[f'{key}_ep'][ep_stock[e]] += 1
        c[f'{key}_ep_hit'][ep_stock[e]] += ep_hit[e]
    return stocks, c


def div(a: float, b: float) -> float:
    return a / b if b else float('nan')


def rates(c: dict, w=None) -> dict:
    tot = {k: float(v.sum() if w is None else (v * w).sum()) for k, v in c.items()}
    out = {key: div(tot[num], tot[den]) for key, _name, num, den in METRICS}
    out['base_opp'] = div(tot['opp'], tot['n'])
    out['base_trap'] = div(tot['trap'], tot['n'])
    out['lift_opp'] = div(out['zone_opp_share'], out['base_opp'])
    out['lift_trap'] = div(out['zone_trap_share'], out['base_trap'])
    return out


def bootstrap(per_label: dict, n_stocks: int) -> dict:
    rng = np.random.default_rng(SEED)
    draws = defaultdict(list)
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, n_stocks, n_stocks), minlength=n_stocks).astype(float)
        for label, c in per_label.items():
            for k, v in rates(c, w).items():
                draws[(label, k)].append(v)
    return draws


def interval(v) -> list:
    a = np.asarray([x for x in v if np.isfinite(x)])
    return [float(np.percentile(a, 5)), float(np.percentile(a, 95))] if len(a) else [None, None]


def by_year(rows, pv, line) -> dict:
    out = defaultdict(Counter)
    for r in rows:
        v = pv.get((r['code'], r['date']))
        zone = v is not None and v <= line
        y = out[r['month'][:4]]
        y['n'] += 1
        y['zone'] += zone
        y['opp'] += r['label'] == OPP
        y['opp_zone'] += r['label'] == OPP and zone
        y['trap_zone'] += r['label'] == TRAP and zone
    return {k: dict(zone_share=v['zone'] / v['n'], opp_capture_m=v['opp_zone'] / v['opp'] if v['opp'] else None,
                    zone_trap_share=v['trap_zone'] / v['zone'] if v['zone'] else None, n=v['n']) for k, v in sorted(out.items())}


def load_cases(path: Path, eps) -> list[dict]:
    spans = defaultdict(list)
    for ep in eps:
        spans[(ep[0]['code'], ep[0]['label'])].append((ep[0]['month'], ep[-1]['month']))
    with path.open(newline='', encoding='utf-8-sig') as f:
        cases = list(csv.DictReader(f))
    for c in cases:
        inside = any(a <= c['window_start'] and c['window_end'] <= b for a, b in spans[(c['security_code'], c['kind'])])
        if not inside:
            raise SystemExit(f"具名案例 {c['case_id']} {c['security_name']} {c['window_start']}～{c['window_end']} 不在同类标签段内")
    return cases


def case_readings(cases, rows, pv, line) -> list[dict]:
    by_code = defaultdict(list)
    for r in rows:
        by_code[r['code']].append(r)
    out = []
    for c in cases:
        w = [r for r in by_code[c['security_code']] if c['window_start'] <= r['month'] <= c['window_end']]
        vals = [(r['month'], pv.get((r['code'], r['date']))) for r in w]
        zone = [m for m, v in vals if v is not None and v <= line]
        finite = [v for _m, v in vals if v is not None]
        out.append(dict(case_id=c['case_id'], months=len(w), zone_months=len(zone), zone_share=len(zone) / len(w) if w else None,
                        first_zone=zone[0] if zone else '', min_pv=min(finite) if finite else None,
                        nopv_months=sum(1 for _m, v in vals if v is None)))
    return out


def load_trades(pattern: str) -> dict:
    out = {}
    for path in sorted(glob.glob(pattern)):
        with open(path, newline='', encoding='utf-8') as f:
            out[path] = [dict(code=r['security_code'].zfill(6), entry=r['entry_date'], exit=r['exit_date'],
                              invested=float(r['invested'] or 0), contrib=float(r['contrib'] or 0)) for r in csv.DictReader(f)]
    return out


def strategy_readings(trades: dict, rows, cases, last_month: str) -> dict:
    """闭合周期按建仓月标签分组：答案卷之后的月份记「未满3年」，答案卷外的记「无标签」。"""
    label_at = {(r['code'], r['month']): r['label'] for r in rows}
    per_start = []
    held = defaultdict(list)
    for _path, cycles in trades.items():
        n, inv, con = Counter(), Counter(), Counter()
        for t in cycles:
            m = t['entry'][:7]
            lab = '未满3年' if m > last_month else label_at.get((t['code'], m), '无标签')
            n[lab] += 1
            inv[lab] += t['invested']
            con[lab] += t['contrib']
        total = sum(inv.values())
        per_start.append(dict(n=n, inv_share={k: v / total for k, v in inv.items()}, contrib=con))
        for c in cases:
            a, b = c['window_start'] + '-01', c['window_end'] + '-31'
            hit = [t for t in cycles if t['code'] == c['security_code'] and t['entry'] <= b and t['exit'] >= a]
            held[c['case_id']].append((bool(hit), sum(t['contrib'] for t in hit)))
    groups = sorted({k for s in per_start for k in s['n']})
    med = lambda xs: statistics.median(xs) if xs else None
    summary = {g: dict(cycles=med([s['n'].get(g, 0) for s in per_start]), invested_share=med([s['inv_share'].get(g, 0.0) for s in per_start]),
                       contrib=med([s['contrib'].get(g, 0.0) for s in per_start])) for g in groups}
    cases_out = {cid: dict(held_starts=sum(h for h, _ in v), starts=len(v), contrib_median=med([x for _, x in v]),
                           contrib_median_held=med([x for h, x in v if h])) for cid, v in held.items()}
    return dict(starts=len(per_start), by_label=summary, cases=cases_out)


def parse_pairs(items, cast=str) -> dict:
    out = {}
    for item in items:
        k, _, v = item.partition('=')
        if not v:
            raise SystemExit(f'参数须为 标签=值：{item}')
        out[k] = cast(v)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--labels', type=Path, default=LABELS)
    ap.add_argument('--cases', type=Path, default=CASES)
    ap.add_argument('--states', nargs='+', required=True, help='标签=逐日状态文件；第一个为对照')
    ap.add_argument('--buy-line', nargs='*', default=[], help='标签=买入线；缺省取生产 SEC93_BUY_LINE')
    ap.add_argument('--trades', nargs='*', default=[], help="标签=*_trades.csv 通配（一个文件一个起点）")
    ap.add_argument('--out', type=Path, required=True, help='报告 .md；同名 .json 存全部读数')
    args = ap.parse_args()
    states = parse_pairs(args.states, Path)
    import screen_daily_volume_price_signals as scanner
    lines = {k: scanner.SEC93_BUY_LINE for k in states} | parse_pairs(args.buy_line, float)
    rows, eps = load_answer_key(args.labels)
    cases = load_cases(args.cases, eps)
    keys = {(r['code'], r['date']) for r in rows}
    last_month = max(r['month'] for r in rows)
    per_label, pvs = {}, {}
    for label, path in states.items():
        pvs[label] = load_pv(path, keys)
        stocks, per_label[label] = counts(rows, pvs[label], lines[label], len(eps))
    draws = bootstrap(per_label, len(stocks))
    ref = next(iter(states))
    result = dict(answer_key=str(args.labels.relative_to(ROOT)) if args.labels.is_relative_to(ROOT) else str(args.labels),
                  months=len(rows), stocks=len(stocks), episodes=dict(Counter(ep[0]['label'] for ep in eps)), lines=lines, labels={})
    for label in states:
        point = rates(per_label[label])
        entry = dict(point=point, ci={k: interval(draws[(label, k)]) for k in point},
                     missing_state=sum(1 for k in keys if k not in pvs[label]),
                     by_year=by_year(rows, pvs[label], lines[label]), cases=case_readings(cases, rows, pvs[label], lines[label]))
        if label != ref:
            entry['delta'] = {k: point[k] - result['labels'][ref]['point'][k] for k in point}
            entry['delta_ci'] = {k: interval(np.subtract(draws[(label, k)], draws[(ref, k)])) for k in point}
        result['labels'][label] = entry
    for item in args.trades:
        label, _, pattern = item.partition('=')
        result['labels'].setdefault(label, {})['strategy'] = strategy_readings(load_trades(pattern), rows, cases, last_month)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float) + '\n')
    args.out.write_text(render(result, cases), encoding='utf-8')
    print(args.out)


def pct(x, d=1):
    return '—' if x is None or x != x else f'{x * 100:.{d}f}%'


def render(res: dict, cases: list[dict]) -> str:
    labels = list(res['labels'])
    ref = labels[0]
    out = [f"# 机会／陷阱读数（§12.1 第 13 款）", '',
           f"答案卷 `{res['answer_key']}`：{res['months']:,} 个在册股票月、{res['stocks']} 只；机会段 {res['episodes'].get(OPP, 0)}、陷阱段 {res['episodes'].get(TRAP, 0)}。"
           f"买入线：{'、'.join(f'{k} {v:.4f}' for k, v in res['lines'].items())}。区间为按股票整簇自助 {BOOT} 次的 5%～95%。", '',
           '无状态行的股票月按无法估值计：' + '、'.join(f"{l} {res['labels'][l]['missing_state']:,}" for l in labels if 'missing_state' in res['labels'][l]) + '。', '',
           '## 估值层', '', '| 读数 | ' + ' | '.join(labels) + (' | 差值（对 ' + ref + '）' if len(labels) > 1 else '') + ' |',
           '| --- |' + ' ---: |' * (len(labels) + (len(labels) > 1))]
    rows = [(k, n) for k, n, _a, _b in METRICS] + [('base_opp', '机会基准率'), ('lift_opp', '买入区机会占比 ÷ 基准率'),
                                                  ('base_trap', '陷阱基准率'), ('lift_trap', '买入区陷阱占比 ÷ 基准率')]
    for key, name in rows:
        cells = []
        for label in labels:
            e = res['labels'][label]
            if 'point' not in e:
                cells.append('—')
                continue
            p, ci = e['point'][key], e['ci'][key]
            fmt = (lambda x: f'{x:.2f}') if key.startswith('lift') else pct
            cells.append(f"{fmt(p)} [{fmt(ci[0])}, {fmt(ci[1])}]")
        if len(labels) > 1:
            e = res['labels'][labels[1]]
            fmt = (lambda x: f'{x:+.2f}') if key.startswith('lift') else (lambda x: f'{x * 100:+.1f}pp')
            cells.append(f"{fmt(e['delta'][key])} [{fmt(e['delta_ci'][key][0])}, {fmt(e['delta_ci'][key][1])}]" if 'delta' in e else '—')
        out.append(f'| {name} | ' + ' | '.join(cells) + ' |')
    for label in labels:
        e = res['labels'][label]
        if 'by_year' not in e:
            continue
        out += ['', f'### 逐年（{label}）', '', '| 年 | 月数 | 买入区占比 | 机会捕捉率（月） | 买入区陷阱占比 |', '| --- | ---: | ---: | ---: | ---: |']
        out += [f"| {y} | {v['n']} | {pct(v['zone_share'])} | {pct(v['opp_capture_m'])} | {pct(v['zone_trap_share'])} |" for y, v in e['by_year'].items()]
    out += ['', '## 具名案例', '', '| 案例 | 公司 | 区间 | 类型 | ' + ' | '.join(f'{l} 买入区月份（首次）' for l in labels) + ' | 最低 P/V |',
            '| --- | --- | --- | --- |' + ' ---: |' * len(labels) + ' ---: |']
    for i, c in enumerate(cases):
        cells = []
        for label in labels:
            e = res['labels'][label]
            if 'cases' not in e:
                cells.append('—')
                continue
            r = e['cases'][i]
            cells.append(f"{r['zone_months']}/{r['months']}" + (f"（{r['first_zone']}）" if r['first_zone'] else '') +
                         (f"，无法估值 {r['nopv_months']}" if r['nopv_months'] else ''))
        mp = res['labels'][ref]['cases'][i]['min_pv']
        out.append(f"| {c['case_id']} {c['kind']} | {c['security_name']} | {c['window_start']}～{c['window_end']} | {c['category']} | "
                   + ' | '.join(cells) + f" | {'—' if mp is None else f'{mp:.2f}'} |")
    for label in labels:
        s = res['labels'][label].get('strategy')
        if not s:
            continue
        out += ['', f"## 策略层（{label}，{s['starts']} 个起点，跨起点中位）", '', '| 建仓月标签 | 周期数 | 投入占比 | contrib 合计 |', '| --- | ---: | ---: | ---: |']
        out += [f"| {g} | {v['cycles']:.0f} | {pct(v['invested_share'])} | {v['contrib'] * 100:+.1f}pp |" for g, v in s['by_label'].items()]
        out += ['', '| 案例 | 公司 | 区间 | 有持仓的起点 | contrib 中位（全部起点） | contrib 中位（持有起点） |', '| --- | --- | --- | ---: | ---: | ---: |']
        for c in cases:
            v = s['cases'][c['case_id']]
            held = v['contrib_median_held']
            out.append(f"| {c['case_id']} {c['kind']} | {c['security_name']} | {c['window_start']}～{c['window_end']} | {v['held_starts']}/{v['starts']} | "
                       f"{v['contrib_median'] * 100:+.2f}pp | {'—' if held is None else f'{held * 100:+.2f}pp'} |")
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    main()

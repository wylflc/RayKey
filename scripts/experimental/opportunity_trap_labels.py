#!/usr/bin/env python3
"""§12.1 第 13 款答案卷（OI-222）：逐月标出其后是优秀便宜机会还是便宜陷阱，只用价格与财报、不读任何估值方法的 `P/V`。

* 观测：回测宇宙 `panel_moat_bank_v6b.csv` 在册期内（与今日名单）每只股票、每个自然月的最后交易日；
* 其后回报：3 年／5 年含分红再投年化总回报（`moat_param_lab.total_return_index`，与公允性检验同一实现）；
  超额 = 3 年年化 − 同月在册股票 3 年年化的中位；
* 盈利变化：观测日与 3 年、5 年后各自已公告的最新归母净利 TTM（`data/raw/financials/` 逐季累计值换算），
  变化率 = (后 − 前) ÷ |前|；供应商把重述旧期的公告日改成重述日，可得日按 `disclosure_dates.available_at` 以法定截止日封顶；
* 分类（阈值 `THRESHOLDS`，唯一定义在工作流程 §12.1 第 13 款）：机会／陷阱／估值扩张／一般；
  同一股票在册月份的同类标签，中断不超过 1 个月合为一段；
* 常规市盈率（月末市值 ÷ 归母净利 TTM）与其同月分位只作候选案例的分组参考，不进分类。

    python3 scripts/experimental/opportunity_trap_labels.py --version v1 \\
        --extra-shares data/experiments/exp_oi222_20260925/share_changes_extra.csv
    # → data/backtest/opportunity_trap_{labels,episodes}_v1.csv、opportunity_trap_summary_v1.json
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
from disclosure_dates import available_at  # noqa: E402
from moat_param_lab import forward_annualized, month_ends, total_return_index  # noqa: E402

PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
TIERS = ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv'
SECURITIES = ROOT / 'data/raw/a_share_securities.csv'
FINANCIALS = ROOT / 'data/raw/financials'
SHARES = ROOT / 'data/raw/share_changes/a_share_share_changes.csv'
OUT_DIR = ROOT / 'data/backtest'
START = '2007-01'
THRESHOLDS = dict(opp_return=0.20, opp_excess=0.10, opp_growth=0.0, trap_return=0.0, trap_excess=-0.10, trap_growth=-0.20)
EPISODE_GAP = 2           # 同类标签相邻两行的月份差 ≤ 2（中断不超过 1 个月）合为一段
TAGS = {'A': 'A现金流复利', 'C': 'C成长', 'D': 'D产业链', 'F': 'F资源', 'K': 'K稳态分配', 'H': 'H周期', 'J': 'J金融', 'E': 'E落难白马'}
OPP, TRAP = '机会', '陷阱'


def label(f3, growth, excess, growth5=None, t=THRESHOLDS):
    """机会的盈利条件取 3 年与 5 年变化的较大者；陷阱只看 3 年。任一必需量缺失返回 None。"""
    if f3 is None or growth is None or excess is None:
        return None
    if f3 >= t['opp_return'] and excess >= t['opp_excess']:
        best = growth if growth5 is None else max(growth, growth5)
        return OPP if best >= t['opp_growth'] else '估值扩张'
    if f3 <= t['trap_return'] and excess <= t['trap_excess'] and growth <= t['trap_growth']:
        return TRAP
    return '一般'


def month_gap(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def episodes(rows: list[dict]) -> list[list[dict]]:
    """在册月份的机会／陷阱行按股票合段；`rows` 须按 (代码, 月份) 升序。"""
    out, by_code = [], defaultdict(list)
    for r in rows:
        if r['panel'] and r['label'] in (OPP, TRAP):
            by_code[r['code']].append(r)
    for rs in by_code.values():
        cur = []
        for r in rs:
            if cur and (r['label'] != cur[-1]['label'] or month_gap(cur[-1]['month'], r['month']) > EPISODE_GAP):
                out.append(cur)
                cur = []
            cur.append(r)
        if cur:
            out.append(cur)
    return out


def load_spans():
    spans, names = defaultdict(list), {}
    with PANEL.open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            code = r['security_code'].zfill(6)
            spans[code].append((r['effective_from'], r.get('effective_to') or '9999-12-31'))
            names[code] = r['security_name']
    return spans, names


def load_profit_ttm(codes: set) -> dict:
    """代码 → [(可得日, 报告期, 归母净利 TTM)]，按可得日升序；缺上年年报或上年同期的季报跳过。"""
    ytd = defaultdict(dict)
    for path in sorted(FINANCIALS.glob('*.csv')):
        with path.open(newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                code = r['security_code'].zfill(6)
                if code not in codes:
                    continue
                try:
                    value = float(r['parent_netprofit'])
                except (TypeError, ValueError):
                    continue
                notice = (r.get('notice_date') or '')[:10]
                if notice:
                    ytd[code][r['report_date'][:10]] = (available_at(r['report_date'][:10], notice), value)
    out = {}
    for code, reports in ytd.items():
        series = []
        for rd, (notice, value) in reports.items():
            year, md = int(rd[:4]), rd[5:]
            if md == '12-31':
                ttm = value
            else:
                fy, same = reports.get(f'{year - 1}-12-31'), reports.get(f'{year - 1}-{md}')
                if not fy or not same:
                    continue
                ttm = value + fy[1] - same[1]
            series.append((notice, rd, ttm))
        series.sort()
        out[code] = series
    return out


def load_shares(codes: set, extra: list[Path]) -> dict:
    out = defaultdict(set)
    for path in (SHARES, *extra):
        if not path.exists():
            continue
        with path.open(newline='', encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                code = r['security_code'].zfill(6)
                try:
                    n = float(r['total_shares'])
                except (TypeError, ValueError):
                    continue
                if code in codes and n > 0:
                    out[code].add((r['effective_date'][:10], n))
    return {code: sorted(v) for code, v in out.items()}


def shares_at(series, day: str):
    n = None
    for d, v in series:
        if d > day:
            break
        n = v
    return n


def profit_at(series, day: str):
    """`day` 当日已公告的最新报告期的 (报告期, TTM)。"""
    best = None
    for notice, rd, ttm in series:
        if notice > day:
            break
        if best is None or rd >= best[0]:
            best = (rd, ttm)
    return best


def shift_years(day: str, years: int) -> str:
    y, m, d = int(day[:4]), day[5:7], day[8:10]
    return f'{y + years}-{m}-{"28" if (m, d) == ("02", "29") else d}'


def growth_between(now, later):
    if now and later and later[0] > now[0] and abs(now[1]) > 0:
        return (later[1] - now[1]) / abs(now[1])
    return None


def build(extra_shares: list[Path]) -> list[dict]:
    spans, panel_names = load_spans()
    tiers = {r['security_code']: r for r in csv.DictReader(TIERS.open(encoding='utf-8-sig'))}
    industry, names = {}, dict(panel_names)
    with SECURITIES.open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            code = r['security_code'].zfill(6)
            industry[code] = r.get('industry') or ''
            names.setdefault(code, r['security_name'])
    codes = set(spans) | set(tiers)
    profits = load_profit_ttm(codes)
    share_hist = load_shares(codes, extra_shares)
    actions = bhv.load_actions()
    rows = []
    for code in sorted(codes):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        days = [d for d, _ in prices]
        tr = total_return_index(prices, actions.get(code, []))
        series = profits.get(code, [])
        close = dict(prices)
        for day in month_ends(days):
            if day[:7] < START:
                continue
            f3, f5 = (forward_annualized(tr, days, day, h) for h in (3, 5))
            now = profit_at(series, day)
            later = profit_at(series, shift_years(day, 3)) if f3 is not None else None
            later5 = profit_at(series, shift_years(day, 5)) if f5 is not None else None
            n = shares_at(share_hist.get(code, []), day)
            pe = close[day] * n / now[1] if n and now and now[1] > 0 else None
            tag = tiers.get(code, {}).get('primary_strategy_tag', '')[:1]
            rows.append(dict(code=code, name=names.get(code, ''), month=day[:7], date=day,
                             panel=any(a <= day <= b for a, b in spans.get(code, ())), pool_today=code in tiers,
                             tier=tiers.get(code, {}).get('quality_tier', ''), tag=TAGS.get(tag, '其他' if tag else ''),
                             industry=industry.get(code, ''), f3=f3, f5=f5,
                             profit_report=now[0] if now else '', profit_ttm=now[1] if now else None,
                             profit_report_3y=later[0] if later else '', profit_ttm_3y=later[1] if later else None,
                             growth3=growth_between(now, later), growth5=growth_between(now, later5),
                             pe_ttm=pe, pe_state='pe' if pe is not None else ('亏损' if now and now[1] <= 0 else '缺数')))
    month_f3, month_pe = defaultdict(list), defaultdict(list)
    for r in rows:
        if r['panel'] and r['f3'] is not None:
            month_f3[r['month']].append(r['f3'])
        if r['panel'] and r['pe_state'] != '缺数':
            month_pe[r['month']].append(r['pe_ttm'] if r['pe_ttm'] is not None else math.inf)   # 亏损记最贵，缺股本不排
    medians = {m: statistics.median(v) for m, v in month_f3.items()}
    for v in month_pe.values():
        v.sort()
    for r in rows:
        v = month_pe.get(r['month'])
        if r['pe_state'] == '缺数' or not v:
            r['pe_rank'] = None
        else:
            x = r['pe_ttm'] if r['pe_ttm'] is not None else math.inf
            r['pe_rank'] = (bisect.bisect_left(v, x) + 0.5 * (bisect.bisect_right(v, x) - bisect.bisect_left(v, x))) / len(v)
        r['f3_excess'] = r['f3'] - medians[r['month']] if r['f3'] is not None and r['month'] in medians else None
        r['label'] = label(r['f3'], r['growth3'], r['f3_excess'], r['growth5'])
    return rows


def episode_rows(rows: list[dict]) -> list[dict]:
    out = []
    for ep in episodes(rows):
        first = ep[0]
        ranks = [r['pe_rank'] for r in ep if r['pe_rank'] is not None]
        out.append(dict(code=first['code'], name=first['name'], label=first['label'], start=first['month'], end=ep[-1]['month'],
                        months=len(ep), f3_median=statistics.median(r['f3'] for r in ep),
                        excess_median=statistics.median(r['f3_excess'] for r in ep),
                        growth_median=statistics.median(r['growth3'] for r in ep), pe_start=first['pe_ttm'],
                        pe_rank_median=statistics.median(ranks) if ranks else None,
                        tier=first['tier'], tag=first['tag'], industry=first['industry'], pool_today=first['pool_today']))
    out.sort(key=lambda e: (e['label'], e['code'], e['start']))
    return out


def write_csv(path: Path, rows: list[dict], prec: int) -> None:
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (f'{v:.{prec}f}' if isinstance(v, float) else v) for k, v in r.items()})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--version', required=True, help='答案卷版本（新版本须用户裁定，旧版本留存）')
    ap.add_argument('--out-dir', type=Path, default=OUT_DIR)
    ap.add_argument('--extra-shares', type=Path, action='append', default=[], help='补充股本变动表（只用于市盈率参考列）')
    args = ap.parse_args()
    rows = build(args.extra_shares)
    eps = episode_rows(rows)
    panel = [r for r in rows if r['panel'] and r['label']]
    by_year = defaultdict(Counter)
    for r in panel:
        by_year[r['month'][:4]][r['label']] += 1
    total = Counter(r['label'] for r in panel)
    summary = dict(version=args.version, thresholds=THRESHOLDS, panel_months=len(panel), panel_stocks=len({r['code'] for r in panel}),
                   months=[min(r['month'] for r in panel), max(r['month'] for r in panel)],
                   base_rates={k: round(v / len(panel), 4) for k, v in sorted(total.items())},
                   by_year={y: dict(c) for y, c in sorted(by_year.items())},
                   episodes=dict(Counter(e['label'] for e in eps)), episodes_3m=dict(Counter(e['label'] for e in eps if e['months'] >= 3)))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / f'opportunity_trap_labels_{args.version}.csv', rows, 6)
    write_csv(args.out_dir / f'opportunity_trap_episodes_{args.version}.csv', eps, 4)
    (args.out_dir / f'opportunity_trap_summary_{args.version}.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({k: summary[k] for k in ('panel_months', 'panel_stocks', 'months', 'base_rates', 'episodes')}, ensure_ascii=False))


if __name__ == '__main__':
    main()

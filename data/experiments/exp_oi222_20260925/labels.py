"""OI-222 草案：与估值方法无关的「答案卷」——逐月标出其后是优秀便宜机会还是便宜陷阱，供用户审定口径与圈定具名案例。

草案口径（待用户审定，阈值集中在 THRESHOLDS）：
* 观测 = 回测宇宙（`panel_moat_bank_v6b.csv` 在册期）与今日名单的每只股票、每个自然月的最后交易日；
* 其后回报 = 3 年（主）／5 年含分红再投年化总回报（`moat_param_lab.total_return_index`，与公允性检验同一实现）；
* 盈利变化 = 观测日与 3 年后各自已公告的最新归母净利 TTM（`data/raw/financials/` 逐季累计值换算；供应商把重述旧期的
  公告日改成重述日，可得日按 `disclosure_dates.available_at` 以法定截止日封顶，与建带同规则），
  变化率 = (后 − 前) ÷ |前|；
* 超额 = 3 年年化 − 同月面板在册股票 3 年年化的中位（剔除整体牛熊，陷阱须是公司自身的问题）；
* 机会 = 3 年年化 ≥ 20%、超额 ≥ +10pp，且 3 年或 5 年后盈利不低于当时（盈利低谷落在 3 年内、其后恢复的仍算）；
  估值扩张 = 同样涨幅但 3 年与 5 年后盈利都更低；
  陷阱 = 3 年年化 ≤ 0、超额 ≤ −10pp 且盈利降 ≥ 20%；其余为一般。`label_abs` 另记只看绝对回报的分类作对照。
* 标签只用价格与财报，不读任何估值方法的 `P/V`，换估值口径时答案卷不变。

    python3 labels.py      # → labels.csv、episodes.csv、candidates.md、summary.json
"""
import bisect
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
from disclosure_dates import available_at  # noqa: E402
from moat_param_lab import forward_annualized, month_ends, total_return_index  # noqa: E402

PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
TIERS = ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv'
SECURITIES = ROOT / 'data/raw/a_share_securities.csv'
FINANCIALS = ROOT / 'data/raw/financials'
SHARES = (ROOT / 'data/raw/share_changes/a_share_share_changes.csv', EXP / 'share_changes_extra.csv')   # 后者为本实验补取的面板股（不动生产表）
CHEAP_PE_RANK = 0.40      # 候选「便宜陷阱」：段内市盈率在同月面板中的分位中位 ≤ 40%（当时看起来便宜）
START = '2007-01'
THRESHOLDS = dict(opp_return=0.20, opp_excess=0.10, opp_growth=0.0, trap_return=0.0, trap_excess=-0.10, trap_growth=-0.20)
GRID_OPP = (0.15, 0.20, 0.25)
GRID_TRAP = (0.0, -0.05, -0.10)
TAGS = {'A': 'A现金流复利', 'C': 'C成长', 'D': 'D产业链', 'F': 'F资源', 'K': 'K稳态分配', 'H': 'H周期', 'J': 'J金融', 'E': 'E落难白马'}


def load_spans():
    spans, names = defaultdict(list), {}
    with PANEL.open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            code = r['security_code'].zfill(6)
            spans[code].append((r['effective_from'], r.get('effective_to') or '9999-12-31'))
            names[code] = r['security_name']
    return spans, names


def load_profit_ttm(codes: set) -> dict:
    """代码 → [(可得日, 报告期, 归母净利 TTM)]，按可得日升序；季度累计值换算 TTM，缺上年年报或同期则跳过该期。"""
    ytd = defaultdict(dict)                  # code → {report_date: (notice_date, ytd)}
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


def load_shares(codes: set) -> dict:
    out = defaultdict(list)
    for path in SHARES:
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
                    out[code].append((r['effective_date'][:10], n))
    for code in out:
        out[code] = sorted(set(out[code]))
    for v in out.values():
        v.sort()
    return out


def shares_at(series, day: str):
    n = None
    for d, v in series:
        if d > day:
            break
        n = v
    return n


def profit_at(series, day: str):
    """`day` 当日已公告的最新报告期的 TTM（同日公告多期取报告期最新者）。"""
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


def label(f3, growth, excess=None, t=THRESHOLDS, opp=None, trap=None, growth5=None):
    """`excess=None` 时只看绝对回报（对照口径）；机会的盈利条件取 3 年与 5 年变化的较大者。"""
    if f3 is None or growth is None:
        return None
    opp = t['opp_return'] if opp is None else opp
    trap = t['trap_return'] if trap is None else trap
    if f3 >= opp and (excess is None or excess >= t['opp_excess']):
        best = growth if growth5 is None else max(growth, growth5)
        return '机会' if best >= t['opp_growth'] else '估值扩张'
    if f3 <= trap and (excess is None or excess <= t['trap_excess']) and growth <= t['trap_growth']:
        return '陷阱'
    return '一般'


def main():
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
    share_hist = load_shares(codes)
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
            growth = growth5 = None
            if now and later and later[0] > now[0] and abs(now[1]) > 0:
                growth = (later[1] - now[1]) / abs(now[1])
            later5 = profit_at(series, shift_years(day, 5)) if f5 is not None else None
            if now and later5 and later5[0] > now[0] and abs(now[1]) > 0:
                growth5 = (later5[1] - now[1]) / abs(now[1])
            tag = tiers.get(code, {}).get('primary_strategy_tag', '')[:1]
            n = shares_at(share_hist.get(code, []), day)
            pe = close[day] * n / now[1] if n and now and now[1] > 0 else None
            pe_state = 'pe' if pe is not None else ('亏损' if now and now[1] <= 0 else '缺数')
            rows.append(dict(code=code, name=names.get(code, ''), month=day[:7], date=day,
                             panel=any(a <= day <= b for a, b in spans.get(code, ())), pool_today=code in tiers,
                             tier=tiers.get(code, {}).get('quality_tier', ''), tag=TAGS.get(tag, '其他' if tag else ''),
                             industry=industry.get(code, ''), f3=f3, f5=f5,
                             profit_report=now[0] if now else '', profit_ttm=now[1] if now else None,
                             profit_report_3y=later[0] if later else '', profit_ttm_3y=later[1] if later else None,
                             growth3=growth, growth5=growth5, pe_ttm=pe, pe_state=pe_state))
    month_f3 = defaultdict(list)
    for r in rows:
        if r['panel'] and r['f3'] is not None:
            month_f3[r['month']].append(r['f3'])
    medians = {m: statistics.median(v) for m, v in month_f3.items()}
    month_pe = defaultdict(list)
    for r in rows:
        if r['panel'] and r['pe_state'] != '缺数':
            month_pe[r['month']].append(r['pe_ttm'] if r['pe_ttm'] is not None else math.inf)   # 亏损记最贵，缺股本不排
    for v in month_pe.values():
        v.sort()
    for r in rows:
        v = month_pe.get(r['month'])
        if r['pe_state'] == '缺数' or not v:
            r['pe_rank'] = None
            continue
        x = r['pe_ttm'] if r['pe_ttm'] is not None else math.inf
        r['pe_rank'] = (bisect.bisect_left(v, x) + 0.5 * (bisect.bisect_right(v, x) - bisect.bisect_left(v, x))) / len(v)
    for r in rows:
        r['f3_excess'] = r['f3'] - medians[r['month']] if r['f3'] is not None and r['month'] in medians else None
        r['label'] = label(r['f3'], r['growth3'], r['f3_excess'], growth5=r['growth5']) if r['f3_excess'] is not None else None
        r['label_abs'] = label(r['f3'], r['growth3'], growth5=r['growth5'])
    fields = list(rows[0])
    with (EXP / 'labels.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f'{v:.6f}' if isinstance(v, float) else v) for k, v in r.items()})

    # 基准率：面板在册月份，按阈值格与年份
    panel = [r for r in rows if r['panel'] and r['label']]
    grid = {}
    for o in GRID_OPP:
        for t in GRID_TRAP:
            c = Counter(label(r['f3'], r['growth3'], r['f3_excess'], opp=o, trap=t, growth5=r['growth5']) for r in panel)
            grid[f'机会≥{o:.0%}｜陷阱≤{t:.0%}'] = {k: round(v / len(panel), 4) for k, v in c.items()}
    by_year, by_year_abs = defaultdict(Counter), defaultdict(Counter)
    for r in panel:
        by_year[r['month'][:4]][r['label']] += 1
        by_year_abs[r['month'][:4]][r['label_abs']] += 1
    summary = dict(thresholds=THRESHOLDS, panel_months=len(panel), panel_stocks=len({r['code'] for r in panel}),
                   months=[min(r['month'] for r in panel), max(r['month'] for r in panel)],
                   base_rates=grid, by_year={y: dict(c) for y, c in sorted(by_year.items())},
                   by_year_abs={y: dict(c) for y, c in sorted(by_year_abs.items())},
                   no_label=sum(1 for r in rows if r['panel'] and r['f3'] is not None and r['label'] is None))

    # 段：同一股票连续月份同一标签（面板在册月），允许中断 1 个月
    episodes = []
    by_code = defaultdict(list)
    for r in rows:
        if r['panel'] and r['label'] in ('机会', '陷阱'):
            by_code[r['code']].append(r)
    for code, rs in by_code.items():
        cur = []
        for r in rs:
            if cur and (r['label'] != cur[-1]['label'] or month_gap(cur[-1]['month'], r['month']) > 2):
                episodes.append(cur)
                cur = []
            cur.append(r)
        if cur:
            episodes.append(cur)
    ep_rows = []
    for ep in episodes:
        f3s = [r['f3'] for r in ep]
        gs = [r['growth3'] for r in ep]
        first = ep[0]
        ep_rows.append(dict(code=first['code'], name=first['name'], label=first['label'], start=first['month'], end=ep[-1]['month'],
                            months=len(ep), f3_median=statistics.median(f3s), excess_median=statistics.median(r['f3_excess'] for r in ep), f3_best=max(f3s) if first['label'] == '机会' else min(f3s),
                            growth_median=statistics.median(gs), pe_start=first['pe_ttm'],
                            pe_rank_median=(statistics.median(ranks) if (ranks := [r['pe_rank'] for r in ep if r['pe_rank'] is not None]) else None),
                            tier=first['tier'], tag=first['tag'], industry=first['industry'],
                            pool_today=first['pool_today']))
    ep_rows.sort(key=lambda e: (e['label'], e['code'], e['start']))
    with (EXP / 'episodes.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(ep_rows[0]))
        w.writeheader()
        for e in ep_rows:
            w.writerow({k: (f'{v:.4f}' if isinstance(v, float) else v) for k, v in e.items()})
    summary['episodes'] = dict(Counter(e['label'] for e in ep_rows))
    summary['episodes_3m'] = dict(Counter(e['label'] for e in ep_rows if e['months'] >= 3))
    (EXP / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n')
    write_candidates(ep_rows)
    print(json.dumps({k: summary[k] for k in ('panel_months', 'panel_stocks', 'months', 'episodes', 'episodes_3m', 'no_label')}, ensure_ascii=False))


def month_gap(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def write_candidates(ep_rows):
    """候选具名案例（盲选：不含任何估值方法的读数）：持续 ≥ 3 个月的段，每股只取最强一段；按当时市盈率在同月面板中的分位
    分成「当时看起来便宜」与「当时不便宜」两组，后者的陷阱是高估值崩塌、不是便宜陷阱，只作对照。"""
    lines = ['# OI-222 候选具名案例（草案，盲选）', '',
             '只列价格、盈利与常规市盈率事实，不含任何估值方法的 `P/V` 读数；请圈定或补充。',
             '「其后3年年化」「超额」取段内各月中位（超额 = 减去同月面板股票的中位）；「净利变化」为段内各月「3 年后 TTM ÷ 当时 TTM − 1」的中位；',
             f'「起点PE」为段首月市值 ÷ 归母净利 TTM（亏损记 —）；「PE分位」为段内各月市盈率在同月面板中的分位中位（0 = 最便宜），≤ {CHEAP_PE_RANK:.0%} 记为当时看起来便宜。',
             '每股至多列两段，按「月数 × |超额|」排序（持续且显著的段在前）。今日档／标签只作分组参考。', '']
    head = ('| # | 公司 | 代码 | 区间 | 月数 | 其后3年年化 | 超额 | 净利变化 | 起点PE | PE分位 | 今日档 | 标签 | 行业 |',
            '| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |')

    def strongest(kind, rev):
        """每股至多两段，按「月数 × |超额|」排序：持续且显著的段在前。"""
        mass = lambda e: e['months'] * abs(e['excess_median'])
        picked, count = [], Counter()
        for e in sorted((e for e in ep_rows if e['label'] == kind and e['months'] >= 3), key=mass, reverse=True):
            if count[e['code']] < 2:
                picked.append(e)
                count[e['code']] += 1
        return picked

    def table(title, eps, limit):
        nonlocal lines
        lines += [f'## {title}（{len(eps)} 只，列前 {min(limit, len(eps))}）', '', *head]
        for i, e in enumerate(eps[:limit], 1):
            pe = f"{e['pe_start']:.1f}" if e['pe_start'] else '—'
            lines.append(f"| {i} | {e['name']} | {e['code']} | {e['start']}～{e['end']} | {e['months']} | {e['f3_median']*100:+.1f}% | "
                         f"{e['excess_median']*100:+.1f}pp | {e['growth_median']*100:+.0f}% | {pe} | {'—' if e['pe_rank_median'] is None else format(e['pe_rank_median'], '.0%')} | "
                         f"{e['tier'] or '—'} | {e['tag'] or '—'} | {e['industry'][:8]} |")
        lines.append('')

    opp, trap = strongest('机会', True), strongest('陷阱', False)
    cheap = lambda e: e['pe_rank_median'] is not None and e['pe_rank_median'] <= CHEAP_PE_RANK
    table('机会·当时看起来便宜', [e for e in opp if cheap(e)], 30)
    table('机会·当时不便宜（按常规市盈率看贵、其后仍大涨且有盈利支撑）', [e for e in opp if not cheap(e)], 30)
    table('便宜陷阱（当时看起来便宜、其后下跌且盈利下滑）', [e for e in trap if cheap(e)], 40)
    table('对照：高估值崩塌（不是便宜陷阱）', [e for e in trap if not cheap(e)], 15)
    (EXP / 'candidates.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()

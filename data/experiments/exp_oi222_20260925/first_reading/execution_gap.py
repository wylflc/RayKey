"""OI-224 证据：估值已判进买入区的机会段，现行 BASE 执行层吃到了多少（14 个标准起点）。

对象：答案卷 v1 的机会段中，生产逐日状态在段内至少一个月末 `P/V` ≤ 买入线的段（「估值已识别」）。
机会期 H = 段内首个进买入区月末 → 段末月末 + 36 个月（机会的其后 3 年回报在此期间兑现）。
逐 (起点, 段)，只计起点早于 H 起点的配对：
  * 是否持有过：有周期与 H 重叠；
  * 进出次数：与 H 重叠的周期数，其中止损退出数；止损后 6 个月含分红总回报；
  * 首次买入：H 起点时未持有者，H 内首个建仓日离「H 起点至建仓日」最低点的涨幅（含分红总回报口径）与等待天数；
  * 在场比例：H 内持有天数 ÷ H 天数；同期买入持有的含分红总回报作参照。

    python3 execution_gap.py    # → execution_gap.json、execution_gap.md
"""
import bisect
import csv
import glob
import json
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
import opportunity_trap_audit as audit  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402
from screen_daily_volume_price_signals import SEC93_BUY_LINE  # noqa: E402

STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
TRADES = sorted(glob.glob(str(HERE / 'bt/*/*_trades.csv')))
PREMIUM = 0.20          # 用户关心的「买入时已涨 20% 以上」
REBOUND = 0.20          # 止损后 6 个月再涨 ≥ 20% 记为「止损后反弹」


def shift(day: str, months: int) -> str:
    y, m = int(day[:4]), int(day[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return f'{y:04d}-{m:02d}-{min(int(day[8:10]), last):02d}'


def at(days, tr, day):
    """≤ day 的最后一个交易日的总回报指数。"""
    i = bisect.bisect_right(days, day) - 1
    return tr[days[i]] if i >= 0 else None


def main():
    rows, eps = audit.load_answer_key(audit.LABELS)
    keys = {(r['code'], r['date']) for r in rows}
    pv = audit.load_pv(STATES, keys)
    recognized = []
    for ep in eps:
        if ep[0]['label'] != audit.OPP:
            continue
        zone = [r for r in ep if (v := pv.get((r['code'], r['date']))) is not None and v <= SEC93_BUY_LINE]
        if zone:
            recognized.append(dict(code=ep[0]['code'], name=ep[0]['name'], tier=ep[0].get('tier', ''), tag=ep[0].get('tag', ''),
                                   start=zone[0]['date'], end=shift(ep[-1]['date'], 36), months=len(ep), zone_months=len(zone)))
    starts = {}
    for path in TRADES:
        start = Path(path).parent.name
        with open(path, newline='', encoding='utf-8') as f:
            starts[start] = [r for r in csv.DictReader(f)]
    actions = bhv.load_actions()
    series = {}
    for code in {e['code'] for e in recognized}:
        prices = bhv.load_ohlcv(code)
        series[code] = ([d for d, _ in prices], total_return_index(prices, actions.get(code, [])))
    pairs = []
    for e in recognized:
        days, tr = series[e['code']]
        span = (date.fromisoformat(min(e['end'], days[-1])) - date.fromisoformat(e['start'])).days
        hold_return = at(days, tr, e['end']) / at(days, tr, e['start']) - 1
        for start, cycles in starts.items():
            if start > e['start']:
                continue
            cs = [c for c in cycles if c['security_code'].zfill(6) == e['code'] and c['entry_date'] <= e['end'] and c['exit_date'] >= e['start']]
            held_days = sum((date.fromisoformat(min(c['exit_date'], e['end'])) - date.fromisoformat(max(c['entry_date'], e['start']))).days for c in cs)
            stops = [c for c in cs if '止损' in c['exit_reason']]
            rebounds = []
            for c in stops:
                a, b = at(days, tr, c['exit_date']), at(days, tr, shift(c['exit_date'], 6))
                if a and b and shift(c['exit_date'], 6) <= days[-1]:
                    rebounds.append(b / a - 1)
            already = any(c['entry_date'] < e['start'] for c in cs)
            first = min((c['entry_date'] for c in cs if c['entry_date'] >= e['start']), default=None)
            premium = delay = None
            if first and not already:
                lo = min(tr[d] for d in days[bisect.bisect_left(days, e['start']):bisect.bisect_right(days, first)])
                premium = at(days, tr, first) / lo - 1
                delay = (date.fromisoformat(first) - date.fromisoformat(e['start'])).days
            pairs.append(dict(code=e['code'], name=e['name'], tag=e['tag'], tier=e['tier'], window=f"{e['start'][:7]}～{e['end'][:7]}", start=start,
                              held=bool(cs), cycles=len(cs), stops=len(stops), rebounds=rebounds, already=already, premium=premium, delay=delay,
                              in_market=held_days / span if span > 0 else None, contrib=sum(float(c['contrib'] or 0) for c in cs),
                              hold_return=hold_return))
    med = lambda xs: statistics.median(xs) if xs else None
    def summarize(ps):
        held = [p for p in ps if p['held']]
        firsts = [p for p in held if p['premium'] is not None]
        rb = [x for p in held for x in p['rebounds']]
        return dict(pairs=len(ps), episodes=len({(p['code'], p['window']) for p in ps}), never_held=1 - len(held) / len(ps) if ps else None,
                    cycles_median=med([p['cycles'] for p in held]), churn_3plus=sum(p['cycles'] >= 3 for p in held) / len(held) if held else None,
                    stop_exits_per_held=sum(p['stops'] for p in held) / len(held) if held else None,
                    rebound_6m_median=med(rb), rebound_share=sum(x >= REBOUND for x in rb) / len(rb) if rb else None, stop_count=len(rb),
                    premium_median=med([p['premium'] for p in firsts]), premium_20plus=sum(p['premium'] >= PREMIUM for p in firsts) / len(firsts) if firsts else None,
                    delay_days_median=med([p['delay'] for p in firsts]), in_market_median=med([p['in_market'] for p in held]),
                    hold_return_median=med([p['hold_return'] for p in ps]))
    groups = {'全部': pairs, '今日 L1': [p for p in pairs if p['tier'] == 'L1'],
              '现金流复利型（今日标签）': [p for p in pairs if p['tag'] == 'A现金流复利'],
              '其余': [p for p in pairs if p['tier'] != 'L1' and p['tag'] != 'A现金流复利']}
    out = dict(buy_line=SEC93_BUY_LINE, recognized_episodes=len(recognized), starts=len(starts), groups={k: summarize(v) for k, v in groups.items()})
    by_ep = defaultdict(list)
    for p in pairs:
        by_ep[(p['name'], p['window'])].append(p)
    worst = sorted(by_ep.items(), key=lambda kv: -statistics.median(p['hold_return'] for p in kv[1]))[:15]
    out['largest'] = [dict(name=k[0], window=k[1], hold_return=statistics.median(p['hold_return'] for p in v), held=sum(p['held'] for p in v), pairs=len(v),
                           cycles=med([p['cycles'] for p in v if p['held']]), premium=med([p['premium'] for p in v if p['premium'] is not None]),
                           contrib=statistics.median(p['contrib'] for p in v)) for k, v in worst]
    (HERE / 'execution_gap.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    pct = lambda x: '—' if x is None else f'{x * 100:.0f}%'
    lines = ['# 估值已识别的机会段：执行层吃到了多少（BASE，14 起点）', '',
             f"对象：答案卷 v1 机会段中至少一个月末 P/V ≤ {SEC93_BUY_LINE:.4f} 的 {len(recognized)} 段；机会期 = 首个进买入区月末 → 段末 + 36 个月；配对只计起点早于机会期的 (起点, 段)。", '',
             '| 组 | 配对 | 段 | 从未持有 | 持有者进出周期中位 | ≥3 个周期 | 每段止损次数 | 止损后 6 个月涨幅中位 | 止损后 6 个月再涨 ≥20% | 首次买入离低点涨幅中位 | 首次买入已涨 ≥20% | 等待天数中位 | 在场比例中位 | 同期买入持有回报中位 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for k, s in out['groups'].items():
        lines.append(f"| {k} | {s['pairs']} | {s['episodes']} | {pct(s['never_held'])} | {s['cycles_median']} | {pct(s['churn_3plus'])} | "
                     f"{s['stop_exits_per_held']:.2f} | {pct(s['rebound_6m_median'])} | {pct(s['rebound_share'])}（{s['stop_count']} 次） | {pct(s['premium_median'])} | "
                     f"{pct(s['premium_20plus'])} | {s['delay_days_median']} | {pct(s['in_market_median'])} | {pct(s['hold_return_median'])} |")
    lines += ['', '## 同期回报最大的 15 段', '', '| 公司 | 机会期 | 同期买入持有 | 持有过的起点 | 周期中位 | 首次买入离低点 | contrib 中位 |', '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    lines += [f"| {x['name']} | {x['window']} | {pct(x['hold_return'])} | {x['held']}/{x['pairs']} | {x['cycles']} | {pct(x['premium'])} | {x['contrib'] * 100:+.2f}pp |" for x in out['largest']]
    (HERE / 'execution_gap.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()

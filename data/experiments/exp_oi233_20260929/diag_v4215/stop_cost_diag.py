"""只读诊断：现行 BASE（v4.215 状态，OI-224 第二批同批）的止损，发生时股票是否仍在买入区、其后走势如何。

输入：exp_oi224_exec2_20260928/trades/<臂>full<起点>_trades.csv（14 起点逐周期），
      exp_land_v4215_20260928/states/H2/a_share_daily_states_hold.csv（持仓侧 P/V），
      答案卷 v1（其后 3 年标签），逐票总回报指数（含分红）。
口径：
  * 止损 = exit_reason 含「止损」；按 (代码, 清仓日) 去重后看其后回报（14 起点多数止损落在同一天同一票）。
  * 区内 = 清仓日持仓侧 P/V ≤ 1.0495（v4.215 买入线）。
  * 其后 k 月回报 = 总回报指数比；对照 = 同一月末全部区内股票（持仓侧 P/V ≤ 线）其后 k 月回报的中位。
  * 重新建仓 = 同起点同票下一周期；溢价 = 重建日总回报指数 ÷ 止损日 − 1。
"""
import bisect
import csv
import glob
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path('/gpfs/scratch1/shared/zwang/mm_quant/RayKey')
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
import opportunity_trap_audit as audit  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402

EXP = ROOT / 'data/experiments/exp_oi224_exec2_20260928'
HOLD = ROOT / 'data/experiments/exp_land_v4215_20260928/states/H2/a_share_daily_states_hold.csv'
LINE = 1.0495
ARMS = sys.argv[1:] or ['BASE']
HORIZONS = (3, 6, 12, 24)


def shift(day: str, months: int) -> str:
    y, m = int(day[:4]), int(day[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return f'{y:04d}-{m:02d}-{min(int(day[8:10]), last):02d}'


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pct(x):
    return '—' if x is None else f'{x * 100:+.1f}%'


def main():
    # 持仓侧 P/V 与 V：代码 → 有序日期列表
    pv = defaultdict(list)
    with HOLD.open(newline='', encoding='utf-8') as f:
        r = csv.reader(f)
        h = next(r)
        ic, idt, ipv, iv = h.index('security_code'), h.index('date'), h.index('valuation_ratio'), h.index('intrinsic_value')
        for row in r:
            try:
                v = float(row[ipv])
            except ValueError:
                v = None
            pv[row[ic]].append((row[idt], v if v and v > 0 else None))
    pv_days = {c: [d for d, _ in xs] for c, xs in pv.items()}

    def pv_at(code, day):
        ds = pv_days.get(code)
        if not ds:
            return None
        i = bisect.bisect_right(ds, day) - 1
        return pv[code][i][1] if i >= 0 else None

    rows, _ = audit.load_answer_key(audit.LABELS)
    label = {(x['code'], x['date']): x['label'] for x in rows}
    all_days = sorted({d for xs in pv_days.values() for d in xs})
    last_in_month = {}
    for d in all_days:
        last_in_month[d[:7]] = d
    month_ends = sorted(last_in_month.values())[:-1]  # 末月未完不作月末

    actions = bhv.load_actions()
    tr_cache = {}

    def series(code):
        if code not in tr_cache:
            prices = bhv.load_ohlcv(code)
            tr = total_return_index(prices, actions.get(code, [])) if prices else {}
            tr_cache[code] = (sorted(tr), tr)
        return tr_cache[code]

    def tr_at(code, day):
        ds, tr = series(code)
        i = bisect.bisect_right(ds, day) - 1
        return (tr[ds[i]], ds[-1]) if i >= 0 else (None, None)

    def fwd(code, day, k):
        a, last = tr_at(code, day)
        end = shift(day, k)
        if a is None or last is None or end > last:
            return None
        b, _ = tr_at(code, end)
        return b / a - 1

    # 同月末区内股票的其后回报中位（对照）
    zone_by_me = defaultdict(list)
    me_set = set(month_ends)
    for code, xs in pv.items():
        for d, v in xs:
            if d in me_set and v is not None and v <= LINE:
                zone_by_me[d].append(code)
    bench = {}

    def bench_at(me, k):
        key = (me, k)
        if key not in bench:
            bench[key] = med([fwd(c, me, k) for c in zone_by_me.get(me, [])])
        return bench[key]

    for arm in ARMS:
        cycles = defaultdict(list)
        for path in sorted(glob.glob(str(EXP / 'trades' / f'{arm}full*_trades.csv'))):
            start = Path(path).name[len(arm) + 4:len(arm) + 12]
            with open(path, newline='', encoding='utf-8') as f:
                for c in csv.DictReader(f):
                    cycles[(start, c['security_code'].zfill(6))].append(c)
        stops, reentry = {}, []
        n_stop_paths = 0
        for (start, code), cs in cycles.items():
            cs.sort(key=lambda c: c['entry_date'])
            for i, c in enumerate(cs):
                if '止损' not in c['exit_reason'] or (__import__('os').environ.get('REASON') and __import__('os').environ['REASON'] not in c['exit_reason']):
                    continue
                n_stop_paths += 1
                key = (code, c['exit_date'])
                stops.setdefault(key, dict(reason=c['exit_reason'], ret=float(c['return_pct'] or 0), days=int(c['holding_days'] or 0)))
                nxt = cs[i + 1] if i + 1 < len(cs) else None
                if nxt:
                    a, _ = tr_at(code, c['exit_date'])
                    b, _ = tr_at(code, nxt['entry_date'])
                    gap = (date.fromisoformat(nxt['entry_date']) - date.fromisoformat(c['exit_date'])).days
                    reentry.append(dict(code=code, gap=gap, prem=(b / a - 1) if a and b else None,
                                        zone=(v := pv_at(code, c['exit_date'])) is not None and v <= LINE))
        # 逐 (代码, 清仓日) 的其后回报
        recs = []
        for (code, day), s in stops.items():
            v = pv_at(code, day)
            me = month_ends[bisect.bisect_right(month_ends, day) - 1] if month_ends and month_ends[0] <= day else None
            rec = dict(code=code, day=day, pv=v, zone=v is not None and v <= LINE, label=label.get((code, me), '无标签'),
                       me=me, ret=s['ret'], days=s['days'], reason=s['reason'])
            for k in HORIZONS:
                rec[f'f{k}'] = fwd(code, day, k)
                rec[f'b{k}'] = bench_at(me, k) if me else None
            recs.append(rec)
        print(f'\n## {arm}：止损 {n_stop_paths} 次（14 起点合计），去重 (代码, 清仓日) {len(recs)} 次')
        zone = [r for r in recs if r['zone']]
        print(f'清仓日仍在买入区（持仓侧 P/V ≤ {LINE}）：{len(zone)}（{len(zone) / len(recs):.0%}）；P/V 中位 {med([r["pv"] for r in recs]):.3f}')
        print(f'周期本身收益中位 {pct(med([r["ret"] for r in recs]))}，持有天数中位 {med([r["days"] for r in recs])}')
        print('\n| 组 | 次数 | 3 月 | 6 月 | 12 月 | 24 月 | 12 月超对照中位 | 12 月 ≥ +20% | 12 月 ≤ −20% |')
        print('| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |')
        groups = [('全部', recs), ('区内', zone), ('区外', [r for r in recs if not r['zone']])]
        for lab in ('机会', '陷阱', '估值扩张', '一般', '无标签'):
            groups.append((f'区内·其后标签={lab}', [r for r in zone if r['label'] == lab]))
        for name, g in groups:
            if not g:
                continue
            ex = [r['f12'] - r['b12'] for r in g if r['f12'] is not None and r['b12'] is not None]
            f12 = [r['f12'] for r in g if r['f12'] is not None]
            print(f"| {name} | {len(g)} | {pct(med([r['f3'] for r in g]))} | {pct(med([r['f6'] for r in g]))} | {pct(med(f12))} | "
                  f"{pct(med([r['f24'] for r in g]))} | {pct(med(ex))} | {sum(x >= 0.2 for x in f12) / len(f12):.0%} | {sum(x <= -0.2 for x in f12) / len(f12):.0%} |"
                  if f12 else f'| {name} | {len(g)} | — | — | — | — | — | — | — |')
        bz = [r['b12'] for r in zone if r['b12'] is not None]
        print(f'\n对照：同月末全部区内股票其后 12 月回报中位的中位 {pct(med(bz))}')
        print('\n| 止损年份 | 次数 | 12 月中位 | 对照中位 | 超对照中位 | 12 月 ≤ −20% | 陷阱标签 |')
        print('| --- | ---: | ---: | ---: | ---: | ---: | ---: |')
        by_year = defaultdict(list)
        for r in zone:
            by_year[r['day'][:4]].append(r)
        for y in sorted(by_year):
            g = by_year[y]
            f12 = [r['f12'] for r in g if r['f12'] is not None]
            ex = [r['f12'] - r['b12'] for r in g if r['f12'] is not None and r['b12'] is not None]
            print(f"| {y} | {len(g)} | {pct(med(f12))} | {pct(med([r['b12'] for r in g]))} | {pct(med(ex))} | "
                  f"{(sum(x <= -0.2 for x in f12) / len(f12)) if f12 else 0:.0%} | {sum(r['label'] == '陷阱' for r in g)} |")
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        f12 = [r['f12'] for r in zone if r['f12'] is not None]
        ex = [r['f12'] - r['b12'] for r in zone if r['f12'] is not None and r['b12'] is not None]
        print(f'\n区内止损其后 12 月均值 {pct(mean(f12))}，超对照均值 {pct(mean(ex))}（n={len(ex)}）')
        for name, g in (('全部', reentry), ('区内止损', [x for x in reentry if x['zone']])):
            gaps = [x['gap'] for x in g]
            prem = [x['prem'] for x in g if x['prem'] is not None]
            within = [x for x in g if x['gap'] <= 365]
            pw = [x['prem'] for x in within if x['prem'] is not None]
            print(f'重新建仓（{name}，逐起点）：{len(g)} 次，间隔中位 {med(gaps)} 天；一年内重建 {len(within)} 次，'
                  f'重建价较止损价（含分红）中位 {pct(med(pw))}，高于止损价的占 {sum(p > 0 for p in pw) / len(pw):.0%}' if pw else f'{name}: 无')


if __name__ == '__main__':
    main()

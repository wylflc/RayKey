"""OI-235 C：P/V 的高估、低估是否有用（preregister.md「P/V 研究」1～5 条），只读，不跑引擎。

样本 = 答案卷行（回测宇宙在册期内每只股票每月最后交易日），`P/V` 取 v4.221 `DC` 候选侧逐日状态，回报为含分红再投总回报
（第 10 款同口径）。分解恒等式：log(P/V₂ ÷ P/V₁) = log(TR₂ ÷ TR₁) − log(Ṽ₂ ÷ Ṽ₁)，Ṽ = TR ÷ (P/V)，即 V 按含派息口径折算。

    python3 pv_study.py     # → pv_study.json、pv_study.md
"""
import bisect
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
sys.path.insert(0, str(EXP))
import build_historical_valuation_bands as bhv  # noqa: E402
import opportunity_trap_audit as audit  # noqa: E402
from moat_param_lab import spearman, total_return_index  # noqa: E402
from run import ACTIONS, LINE, STATES  # noqa: E402

HIGH = 1.30
BUCKETS = (('≤0.70', 0.0, 0.70), ('0.70～1.0034', 0.70, LINE), ('1.0034～1.30', LINE, HIGH), ('1.30～1.60', HIGH, 1.60), ('>1.60', 1.60, 1e9))


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def mindex(d):
    return int(d[:4]) * 12 + int(d[5:7]) - 1


def shift(day, months):
    y, m = int(day[:4]), int(day[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return f'{y:04d}-{m:02d}-{min(int(day[8:10]), last):02d}'


def main():
    rows, _eps = audit.load_answer_key(audit.LABELS)
    pv = audit.load_pv(STATES / 'a_share_daily_states_adopted.csv', {(r['code'], r['date']) for r in rows})
    bhv.ACTIONS = ACTIONS
    actions = bhv.load_actions()
    series = {}
    for code in {r['code'] for r in rows}:
        px = bhv.load_ohlcv(code)
        if px:
            series[code] = ([d for d, _ in px], total_return_index(px, actions.get(code, [])))
    last_day = max(ds[-1] for ds, _ in series.values())

    def tr(code, d):
        days, t = series[code]
        i = bisect.bisect_right(days, d) - 1
        return t[days[i]] if i >= 0 else None

    def fwd(code, d, k):
        if code not in series or shift(d, k) > last_day:
            return None
        a, b = tr(code, d), tr(code, shift(d, k))
        return b / a - 1 if a and b else None
    by_code = defaultdict(list)
    for r in rows:
        v = pv.get((r['code'], r['date']))
        if r['code'] in series:
            by_code[r['code']].append((r['date'], v if v and v > 0 else None, r))
    for xs in by_code.values():
        xs.sort(key=lambda x: x[0])
    month_rows = defaultdict(list)            # 月末 → [(代码, P/V)]
    for code, xs in by_code.items():
        for d, v, _ in xs:
            if v is not None:
                month_rows[d].append((code, v))
    f12_cache = {}

    def f12(code, d):
        if (code, d) not in f12_cache:
            f12_cache[(code, d)] = fwd(code, d, 12)
        return f12_cache[(code, d)]
    zone_bench, all_bench = {}, {}

    def bench(d, zone_only):
        cache = zone_bench if zone_only else all_bench
        if d not in cache:
            cache[d] = med([f12(c, d) for c, v in month_rows.get(d, []) if (v <= LINE or not zone_only)])
        return cache[d]

    # 3. 分档前向回报
    tiers = {}
    for name, lo, hi in BUCKETS:
        ex12, a12, a36, ex36 = [], [], [], []
        for d, lst in month_rows.items():
            for code, v in lst:
                if not (lo < v <= hi):
                    continue
                x = f12(code, d)
                if x is not None and (b := bench(d, False)) is not None:
                    a12.append(x)
                    ex12.append(x - b)
        for code, xs in by_code.items():
            for d, v, r in xs:
                if v is not None and lo < v <= hi and r.get('f3') not in (None, ''):
                    a36.append(float(r['f3']))
                    if r.get('f3_excess') not in (None, ''):
                        ex36.append(float(r['f3_excess']))
        tiers[name] = dict(n12=len(a12), fwd12=med(a12), excess12=med(ex12), n36=len(a36), fwd36_ann=med(a36), excess36_ann=med(ex36))
    pairs = [(v, f) for d, lst in month_rows.items() for code, v in lst if (f := f12(code, d)) is not None]
    rho12 = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    pairs36 = [(v, float(r['f3'])) for xs in by_code.values() for d, v, r in xs if v is not None and r.get('f3') not in (None, '')]
    rho36 = spearman([p[0] for p in pairs36], [p[1] for p in pairs36])

    # 1、2、4. 区内段：进区 → 其后首个有观测且 > 买入线的月末（出线）；中间无估值或不在册的月份跳过，
    # 断档超过 12 个月或到数据末端仍未出线记截尾。进区 = 不在进行中的段时，首个 ≤ 买入线的月末。
    episodes = []
    for code, xs in by_code.items():
        obs = [(d, v, r) for d, v, r in xs if v is not None]
        i = 0
        while i < len(obs):
            d, v, r = obs[i]
            if v > LINE:
                i += 1
                continue
            ep = dict(code=code, name=r['name'], industry=r['industry'], entry=d, entry_pv=v, exit=None)
            j, months_in, censored = i, 1, False
            while j + 1 < len(obs):
                if mindex(obs[j + 1][0]) - mindex(obs[j][0]) > 12:
                    censored = True
                    break
                j += 1
                if obs[j][1] > LINE:
                    break
                months_in += 1
            if not censored and obs[j][1] > LINE and j > i:
                ed, ev, _ = obs[j]
                ep.update(exit=ed, exit_pv=ev)
                t0, t1 = tr(code, d), tr(code, ed)
                ep['dlog_tr'] = math.log(t1 / t0)
                ep['dlog_v'] = math.log((t1 / ev) / (t0 / v))
                ep['exit_f12'] = f12(code, ed)
                zb = bench(ed, True)
                ep['exit_excess12'] = ep['exit_f12'] - zb if ep['exit_f12'] is not None and zb is not None else None
            ep['months_in'] = months_in
            later = [(x[0], x[1]) for x in obs[i:] if mindex(x[0]) - mindex(d) <= 36]
            ep['max_pv_36m'] = max(p for _, p in later)
            ep['first_high'] = next((x[0] for x in later if x[1] > HIGH), None)
            ep['observed_36m'] = shift(d, 36) <= obs[-1][0] and not (censored and mindex(obs[j][0]) - mindex(d) < 36)
            ep['f3'] = float(r['f3']) if r.get('f3') not in (None, '') else None
            episodes.append(ep)
            i = j + 1 if ep['exit'] or censored else len(obs)
    exits = [e for e in episodes if e['exit']]
    price_led = [e for e in exits if max(0.0, e['dlog_tr']) >= max(0.0, -e['dlog_v'])]
    v_led = [e for e in exits if e not in price_led]
    observed = [e for e in episodes if e['observed_36m']]

    def within(e, k):
        return e['exit'] is not None and mindex(e['exit']) - mindex(e['entry']) <= k
    stay = dict(n=len(observed), exit_12m=sum(within(e, 12) for e in observed) / len(observed),
                exit_24m=sum(within(e, 24) for e in observed) / len(observed), exit_36m=sum(within(e, 36) for e in observed) / len(observed),
                high_36m=sum(e['first_high'] is not None for e in observed) / len(observed),
                months_to_exit=med([mindex(e['exit']) - mindex(e['entry']) for e in exits]))
    never = [e for e in observed if not within(e, 36)]
    never_f3 = [e['f3'] for e in never if e['f3'] is not None]

    def grp(es):
        return dict(n=len(es), dlog_tr=med([e['dlog_tr'] for e in es]), dlog_v=med([e['dlog_v'] for e in es]),
                    f12=med([e['exit_f12'] for e in es]), excess12=med([e['exit_excess12'] for e in es]),
                    excess12_pos=(sum(e['exit_excess12'] > 0 for e in es if e['exit_excess12'] is not None)
                                  / max(1, sum(e['exit_excess12'] is not None for e in es))))
    decomposition = dict(all=grp(exits), price_led=grp(price_led), v_led=grp(v_led),
                         v_fell_share=sum(e['dlog_v'] < 0 for e in exits) / len(exits),
                         price_rose_share=sum(e['dlog_tr'] > 0 for e in exits) / len(exits))

    # 5. 长期低 P/V 名单
    longcheap = []
    for code, xs in by_code.items():
        obs = [(d, v) for d, v, _ in xs if v is not None]
        if len(obs) < 60:
            continue
        share = sum(v <= LINE for _, v in obs) / len(obs)
        if share < 0.8:
            continue
        (d0, v0), (d1, v1) = obs[0], obs[-1]
        yrs = (date.fromisoformat(d1) - date.fromisoformat(d0)).days / 365.25
        t0, t1 = tr(code, d0), tr(code, d1)
        longcheap.append(dict(code=code, name=xs[0][2]['name'], industry=xs[0][2]['industry'], months=len(obs), zone_share=share,
                              first=d0, last=d1, pv_first=v0, pv_last=v1, pv_max=max(v for _, v in obs),
                              tr_ann=(t1 / t0) ** (1 / yrs) - 1, v_ann=((t1 / v1) / (t0 / v0)) ** (1 / yrs) - 1))
    longcheap.sort(key=lambda x: -x['zone_share'])
    res = dict(line=LINE, sample_rows=sum(len(v) for v in month_rows.values()), codes=len(by_code), last_day=last_day,
               tiers=tiers, spearman12=rho12, spearman36=rho36, stay=stay, never_n=len(never), never_f3_median=med(never_f3),
               never_f3_pos=sum(x > 0 for x in never_f3) / len(never_f3) if never_f3 else None, decomposition=decomposition,
               longcheap=longcheap, never_examples=sorted(({k: e[k] for k in ('code', 'name', 'industry', 'entry', 'entry_pv', 'max_pv_36m', 'f3')}
                                                          for e in never), key=lambda e: e['entry'])[-40:])
    (EXP / 'pv_study.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    write_md(res)


def write_md(res):
    pct = lambda x, d=1: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x: '—' if x is None else f'{x * 100:+.1f}pp'
    out = [f"# OI-235 C：P/V 高估、低估是否有用（v4.221 DC 候选侧，{res['sample_rows']} 个股票月，{res['codes']} 只）", '',
           '## 一、分档前向回报（全部在册股票月）', '',
           f"12 个月 Spearman(P/V, 回报) = {res['spearman12']:+.3f}；3 年年化 Spearman = {res['spearman36']:+.3f}。超额 = 减同月全部在册股票中位。", '',
           '| 月末 P/V | 股票月 | 其后 12 月中位 | 12 月超额中位 | 其后 3 年年化中位 | 3 年年化超额中位 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name, t in res['tiers'].items():
        out.append(f"| {name} | {t['n12']} | {pct(t['fwd12'])} | {pp(t['excess12'])} | {pct(t['fwd36_ann'])} | {pp(t['excess36_ann'])} |")
    s = res['stay']
    out += ['', '## 二、进区之后：多久出线（月末首次 > 买入线）', '',
            f"有 36 个月观测的进区段 {s['n']} 个：12 个月内出线 {pct(s['exit_12m'], 0)}、24 个月 {pct(s['exit_24m'], 0)}、36 个月 {pct(s['exit_36m'], 0)}；"
            f"36 个月内 P/V 到过 1.30 以上 {pct(s['high_36m'], 0)}；出线段的进区到出线中位 {s['months_to_exit']} 个月。",
            f"36 个月内始终没出线的 {res['never_n']} 段：进区时其后 3 年含分红年化中位 {pct(res['never_f3_median'])}，为正的占 {pct(res['never_f3_pos'], 0)}。", '',
            '## 三、出线靠什么：价格上涨还是 V 下降', '',
            'log(P/V 变化) = log(含分红总回报) − log(V 变化)，按进区月到出线月计；价格驱动 = 总回报上涨部分 ≥ V 下降部分。'
            '「出线后 12 月超额」= 出线月起 12 个月回报减同月区内股票中位（卖出后换成其它区内股票的相对得失，负值说明卖出换仓更好）。', '',
            '| 组 | 段数 | 总回报 log 变化中位 | V log 变化中位 | 出线后 12 月回报中位 | 出线后 12 月超额中位 | 超额为正占比 |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    dec = res['decomposition']
    for key, name in (('all', '全部出线'), ('price_led', '价格驱动'), ('v_led', 'V 驱动')):
        g = dec[key]
        out.append(f"| {name} | {g['n']} | {g['dlog_tr']:+.3f} | {g['dlog_v']:+.3f} | {pct(g['f12'])} | {pp(g['excess12'])} | {pct(g['excess12_pos'], 0)} |")
    out += ['', f"出线段里 V 下降的占 {pct(dec['v_fell_share'], 0)}，总回报上涨的占 {pct(dec['price_rose_share'], 0)}。", '',
            '## 四、进区后 36 个月内始终没出线的段', '',
            '| 股票 | 行业 | 进区月 | 进区 P/V | 36 个月内最高 P/V | 进区月其后 3 年含分红年化 |', '| --- | --- | --- | ---: | ---: | ---: |']
    for e in res['never_examples']:
        out.append(f"| {e['name']}（{e['code']}） | {e['industry']} | {e['entry'][:7]} | {e['entry_pv']:.2f} | "
                   f"{e['max_pv_36m']:.2f} | {pct(e['f3'])} |")
    out += ['', '## 五、长期低 P/V（在册 ≥ 60 个月且 ≥ 80% 的月份在区内）', '',
            '| 股票 | 行业 | 月数 | 区内占比 | 起止 | P/V 首／末／最高 | 期间含分红年化 | V 年化（含派息） |', '| --- | --- | ---: | ---: | --- | --- | ---: | ---: |']
    for x in res['longcheap']:
        out.append(f"| {x['name']}（{x['code']}） | {x['industry']} | {x['months']} | {pct(x['zone_share'], 0)} | {x['first'][:7]}～{x['last'][:7]} | "
                   f"{x['pv_first']:.2f}／{x['pv_last']:.2f}／{x['pv_max']:.2f} | {pct(x['tr_ann'])} | {pct(x['v_ann'])} |")
    (EXP / 'pv_study.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()

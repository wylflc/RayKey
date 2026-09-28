"""OI-230 估值层读数 V1、V2、V4（银行子集）、V5（preregister.md）；V3 见 calibrate_k.py 的 calibration.json。

    python3 valuation.py    # → valuation.json、valuation.md

臂的状态取 states/<臂>_build 的候选侧逐日文件（全市场）：CONTROL 与 DC_RAW／CONTROL_RAW 的排序相同（k 为常数），
V1、V2 用 CONTROL 与 DC；V4 用 CONTROL（1.0034）、DC_K0（1.0034）与 DC（L1）；V5 用 DC（L1）。
"""
import bisect
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import bank_valuation  # noqa: E402
import build_historical_valuation_bands as bhv  # noqa: E402
import opportunity_trap_audit as audit  # noqa: E402
from moat_param_lab import forward_annualized, total_return_index  # noqa: E402

PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
BANDS = EXP / 'old_inputs/data/processed/roic_bands.csv'
START = '2010-01'
HORIZONS = (1, 2, 3)
NAMED = {'000001': '平安银行', '600016': '民生银行', '600036': '招商银行', '601398': '工商银行'}


def states(arm):
    return EXP / 'states' / f'{arm}_build' / 'a_share_daily_states_adopted.csv'


def month_end_pv(path, codes):
    """{(代码, 月): (日, P/V)}：银行行的月末 P/V（2007 年起）。"""
    ends = {}
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        h = next(reader)
        ic, idt, ipv = (h.index(k) for k in ('security_code', 'date', 'valuation_ratio'))
        for row in reader:
            if row[ic] not in codes or row[idt] < '2007-01-01' or not row[ipv]:
                continue
            pv = float(row[ipv])
            if pv <= 0:
                continue
            key = (row[ic], row[idt][:7])
            if key not in ends or row[idt] > ends[key][0]:
                ends[key] = (row[idt], pv)
    return ends


def spearman(x, y):
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def nw_t(series, lag):
    x = np.asarray(series, float)
    n = len(x)
    if n < 3:
        return None
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n)) if var > 0 else None


def spans():
    out = defaultdict(list)
    with PANEL.open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            out[r['security_code'].zfill(6)].append((r['effective_from'], r.get('effective_to') or '9999-12-31'))
    return out


def main():
    banks = bank_valuation.bank_codes(ROOT / 'data/raw/a_share_securities.csv')
    align = json.loads((EXP / 'align_check.json').read_text())
    l1, line = align['l1'], align['current_line']
    pv = {arm: month_end_pv(states(arm), banks) for arm in ('CONTROL', 'DC', 'DC_K0')}
    fund = bank_valuation.BankFundamentals(BANDS, banks)
    sp = spans()
    actions = bhv.load_actions()
    fwd = {}
    for code in sorted({k[0] for k in pv['CONTROL']} | {k[0] for k in pv['DC']}):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        days = [d for d, _ in prices]
        tr = total_return_index(prices, actions.get(code, []))
        for key in {k for k in pv['CONTROL'] if k[0] == code} | {k for k in pv['DC'] if k[0] == code}:
            day = (pv['CONTROL'].get(key) or pv['DC'][key])[0]
            if day in tr:
                fwd[key] = {h: forward_annualized(tr, days, day, h) for h in HORIZONS}
    res = dict(line=line, l1=l1, banks=len(banks))
    # ---- V1 机制：逐月截面派息率与 P/V 的秩相关 ----
    v1 = {}
    for arm in ('CONTROL', 'DC'):
        by_month = defaultdict(list)
        for (code, month), (day, x) in pv[arm].items():
            f = fund.at(code, day)
            if f and f[3] is not None:
                by_month[month].append((f[3], x))
        rhos = [spearman([a for a, _ in v], [b for _, b in v]) for m, v in sorted(by_month.items()) if len(v) >= 10 and m >= START]
        v1[arm] = dict(months=len(rhos), median=statistics.median(rhos), p10=float(np.percentile(rhos, 10)), p90=float(np.percentile(rhos, 90)),
                       negative_share=sum(r < 0 for r in rhos) / len(rhos))
    res['V1_payout_pv_rank'] = v1
    res['V1_named'] = {}
    for code, name in NAMED.items():
        res['V1_named'][name] = {m[:4]: {arm: round(pv[arm][(code, m)][1], 3) if (code, m) in pv[arm] else None for arm in ('CONTROL', 'DC')}
                                 for m in sorted({k[1] for k in pv['CONTROL'] if k[0] == code} | {k[1] for k in pv['DC'] if k[0] == code})
                                 if m.endswith('-12') and m >= '2010-12'}
    # ---- V2 银行内排序 ----
    v2 = {}
    for panel_only in (False, True):
        for h in HORIZONS:
            by_month = defaultdict(list)
            for key in pv['CONTROL'].keys() & pv['DC'].keys():
                code, month = key
                f = (fwd.get(key) or {}).get(h)
                if f is None or month < START:
                    continue
                day = pv['CONTROL'][key][0]
                if panel_only and not any(a <= day <= b for a, b in sp.get(code, ())):
                    continue
                by_month[month].append((pv['CONTROL'][key][1], pv['DC'][key][1], f))
            ic_c, ic_d = [], []
            for _m, v in sorted(by_month.items()):
                if len(v) < 10:
                    continue
                y = [x[2] for x in v]
                ic_c.append(spearman([math.log(x[0]) for x in v], y))
                ic_d.append(spearman([math.log(x[1]) for x in v], y))
            diff = [d - c for c, d in zip(ic_c, ic_d)]
            v2[f"{'panel' if panel_only else 'all'}_{h}y"] = dict(
                months=len(diff), control=float(np.mean(ic_c)), control_t=nw_t(ic_c, 12 * h), dc=float(np.mean(ic_d)), dc_t=nw_t(ic_d, 12 * h),
                diff=float(np.mean(diff)), diff_t=nw_t(diff, 12 * h), dc_better_share=sum(x < 0 for x in diff) / len(diff))
    res['V2_bank_ranking'] = v2
    # ---- V4 银行子集第 13 款估值层（OI-227 bank_zone 同式）----
    rows, _eps = audit.load_answer_key(audit.LABELS)
    bank_rows = [r for r in rows if r['code'] in banks]
    eps = sorted({r['episode'] for r in bank_rows if 'episode' in r})
    remap = {e: i for i, e in enumerate(eps)}
    local = [dict(r, episode=remap[r['episode']]) if 'episode' in r else r for r in bank_rows]
    keys = {(r['code'], r['date']) for r in bank_rows}
    v4 = {}
    arm_pv = {}
    for arm, ln in (('CONTROL', line), ('DC_K0', line), ('DC', l1)):
        arm_pv[arm] = audit.load_pv(states(arm), keys)
        stocks, c = audit.counts(local, arm_pv[arm], ln, len(eps))
        point = audit.rates(c)
        draws = audit.bootstrap({'x': c}, len(stocks))
        v4[f'{arm}@{ln}'] = {k: dict(point=point.get(k), ci=audit.interval(draws[('x', k)])) for k in point}
    res['V4_bank_zone'] = v4
    res['V4_bank_rows'], res['V4_bank_stocks'] = len(bank_rows), len({r['code'] for r in bank_rows})
    # ---- V5 低派息银行在 DC 买入区 ----
    groups = defaultdict(list)
    for r in bank_rows:
        x = arm_pv['DC'].get((r['code'], r['date']))
        if x is None or x > l1 or not r.get('label'):
            continue
        f = fund.at(r['code'], r['date'])
        payout = f[3] if f else None
        g = 'payout<20%' if payout is not None and payout < 0.20 else ('payout≥20%' if payout is not None else 'payout缺')
        c = arm_pv['CONTROL'].get((r['code'], r['date']))
        groups[g].append(dict(code=r['code'], label=r['label'], f3=float(r['f3']) if r.get('f3') not in (None, '', 'None') else None,
                              in_control_zone=c is not None and c <= line))
    v5 = {}
    for g, v in groups.items():
        f3 = [x['f3'] for x in v if x['f3'] is not None]
        v5[g] = dict(months=len(v), stocks=len({x['code'] for x in v}), opp_share=sum(x['label'] == '机会' for x in v) / len(v),
                     trap_share=sum(x['label'] == '陷阱' for x in v) / len(v), f3_median=statistics.median(f3) if f3 else None,
                     also_in_control_zone=sum(x['in_control_zone'] for x in v) / len(v),
                     stock_months=dict(sorted(((c, sum(1 for x in v if x['code'] == c)) for c in {x['code'] for x in v}), key=lambda kv: -kv[1])[:8]))
    res['V5_payout_split'] = v5
    (EXP / 'valuation.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    pct = lambda x: '—' if x is None else f'{x * 100:.1f}%'
    out = ['# OI-230 估值层读数', '', f'现行线 {line}，L1 {l1}；银行 {len(banks)} 只（不含保险）。', '',
           '## V1 派息率与 P/V 的逐月截面秩相关（2010 年起，每月至少 10 家）', '', '| 臂 | 月数 | 中位 | P10～P90 | 为负的月份 |', '| --- | ---: | ---: | --- | ---: |']
    for arm, e in v1.items():
        out.append(f"| {arm} | {e['months']} | {e['median']:.3f} | {e['p10']:.3f}～{e['p90']:.3f} | {pct(e['negative_share'])} |")
    out += ['', '## V2 银行内排序（log P/V 对其后年化回报的截面 Spearman，逐月均值；t 为 Newey-West）', '',
            '| 样本 | 月数 | CONTROL（t） | DC（t） | DC − CONTROL（t） | DC 更负的月份 |', '| --- | ---: | --- | --- | --- | ---: |']
    for k, e in v2.items():
        out.append(f"| {k} | {e['months']} | {e['control']:.3f}（{e['control_t']:.2f}） | {e['dc']:.3f}（{e['dc_t']:.2f}） | {e['diff']:+.3f}（{e['diff_t']:+.2f}） | {pct(e['dc_better_share'])} |")
    out += ['', f"## V4 银行子集第 13 款（答案卷银行股票月 {res['V4_bank_rows']}，{res['V4_bank_stocks']} 只；整簇自助 5%～95%）", '',
            '| 臂@线 | 买入区占比 | 机会捕捉（月） | 机会捕捉（段） | 买入区机会占比 | 买入区陷阱占比 | 机会 ÷ 基准 | 陷阱 ÷ 基准 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key, e in v4.items():
        cell = lambda k, f=pct: f"{f(e[k]['point'])} [{f(e[k]['ci'][0])}, {f(e[k]['ci'][1])}]" if k in e else '—'
        ratio = lambda x: '—' if x is None or x != x else f'{x:.2f}'
        out.append(f"| {key} | {cell('zone_share')} | {cell('opp_capture_m')} | {cell('opp_capture_e')} | {cell('zone_opp_share')} | "
                   f"{cell('zone_trap_share')} | {cell('lift_opp', ratio)} | {cell('lift_trap', ratio)} |")
    out += ['', '## V5 DC 买入区内的低派息银行（答案卷有标签的银行股票月）', '',
            '| 分组 | 月数 | 股票 | 机会占比 | 陷阱占比 | 其后 3 年年化中位 | 同月也在 CONTROL 买入区 |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for g, e in sorted(v5.items()):
        out.append(f"| {g} | {e['months']} | {e['stocks']} | {pct(e['opp_share'])} | {pct(e['trap_share'])} | {pct(e['f3_median'])} | {pct(e['also_in_control_zone'])} |")
    out += ['', '## 具名银行年末 P/V（CONTROL → DC）', '']
    for name, path in res['V1_named'].items():
        out.append(f"- {name}：" + '；'.join(f"{y} {v['CONTROL']}→{v['DC']}" for y, v in path.items()))
    (EXP / 'valuation.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()

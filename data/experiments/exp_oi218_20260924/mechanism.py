"""OI-218 机制层核对（不看回测收益）。实际值取三大报表年报（nonop 口径、投入资本下限 0.1 × 总权益、公告日封顶），非金融。

M1 增长的代价：生产候选侧历史带（`roic_bands.csv`）年报行、增长路径、资本腿 g0 > 0，按最新年报「原投入资本
   （有息负债 + 总权益 − 超额现金）< 0.1 × 总权益」分触下限／未触下限。比较其后 5 年
   ① 实际再投资占比 = Σ(资本开支 − 折旧摊销 + ΔWC) ÷ ΣNOPAT，② 实际 NOPAT 年化增长（t → t+5），
   ③ 实际自由现金 Σ(NOPAT − 再投资) ÷ NOPAT_t，
   与引擎（生产参数）按带参数给出的前 5 年留存均值、增长与自由现金；候选 A1 = 留存按资本腿增量回报收
   （回报路径起点 min(增量 ROIC, 40%, ROIC0)），A0 = g0 = 0。
   M1b 全部资本腿增长行（年报行）：按 g0、增量 ROIC 封顶、低基数（窗口首年 NOPAT < 后四年中位一半）分组，
   实际 5 年 NOPAT 年化 vs 引擎；按「再投资率 − 引擎前 5 年留存」分组，A1' = 前 5 年留存取两者较大、增长不变。
   M1c 资本腿乘增速腿折减 d（年报行与季报行，季报行自最新年报起算 5 年）：引擎 5 年增长 vs 实际。
M2 负营运资本（供应商与经销商垫款）的持续性：原投入资本 < 下限的非金融公司年报行，其后 3／5 年
   垫款（−营运资本）与营收的变化，垫款收缩超过 25% 的比例及当时营收变化。
M3 λ = 0 的锚：比率 = NOPAT ÷ 母公司权益（经营账面的外生权益调整忽略）。
   年报行：近两次变动均不上行（λ = 0）且峰谷权重为 0（与生产 median3 同），锚 = 三年中位；候选 当期、两者均值。
   季报行：生产带 `roic_nopat_mode = median3` 的季报行，当期 = 最新年报比率 × TTM 因子。
   实际 = 其后 3 年比率均值（年报行自 t+1、季报行自报告年起），另报第二口径（其后 NOPAT 均值 ÷ 当年权益）。
    python3 mechanism.py        # writes mechanism.json and mechanism.txt
"""
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
from intrinsic_value import ValuationError, intrinsic_value  # noqa: E402
import roic_inputs  # noqa: E402

FLOOR = 0.1
LINES, RESULT = [], {}


def out(line=''):
    LINES.append(line)
    print(line, flush=True)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fmt(x, pct=True):
    return '—' if x is None else (f'{x:+.1%}' if pct else f'{x:.2f}')


def annual(stmts):
    """{code: {year: RoicYear}}，非金融、年报。"""
    res = {}
    for code, years in stmts.items():
        if any(y.is_financial for y in years.values()):
            continue
        res[code] = {int(p[:4]): y for p, y in years.items() if p.endswith('-12-31')}
    return res


def raw_ic(y):
    if y.total_equity is None:
        return None
    return y.interest_debt + y.total_equity - y.excess_cash


def floored(y):
    ic = raw_ic(y)
    return ic is not None and y.total_equity > 0 and ic < FLOOR * y.total_equity


def engine(roic0, g0, w):
    return intrinsic_value(1.0, roic0, g0, w, roe_terminal=min(w + 0.02, roic0), g_terminal=0.03, n=10, n1=0,
                           consistent=True, roe_lam=0.12, horizon=50)


def forward_cash(ys, t, h=5):
    seq = [ys.get(t + i) for i in range(0, h + 1)]
    if any(y is None or y.nopat is None or y.working_capital is None for y in seq) or seq[0].nopat <= 0:
        return None
    nopat = sum(y.nopat for y in seq[1:])
    reinv = sum(y.capex - y.dep_amort for y in seq[1:]) + seq[-1].working_capital - seq[0].working_capital
    if nopat <= 0 or seq[-1].nopat <= 0:
        return None
    return dict(reinv_share=reinv / nopat, cagr=(seq[-1].nopat / seq[0].nopat) ** (1 / h) - 1,
                fcf=(nopat - reinv) / seq[0].nopat, nopat_sum=nopat / seq[0].nopat)


def m1(ann):
    out('## M1 资本腿增长的代价：引擎留存 vs 其后实际再投资（历史带年报行，g0 > 0 且来自资本腿）')
    recs = []
    with (ROOT / 'data/processed/roic_bands.csv').open(encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if (r['status'] != 'ok' or r['roic_path'] != 'growth' or not r['report_date'].endswith('-12-31')
                    or r['roic_g_source'] != 'capital'):
                continue
            g0, roic0, w, iroic, rr = (fnum(r[k]) for k in ('g0', 'roic0', 'wacc', 'incremental_roic', 'reinvestment_rate'))
            code, t = r['security_code'], int(r['report_date'][:4])
            ys = ann.get(code)
            if not g0 or g0 <= 0 or None in (roic0, w, iroic, rr) or not ys or t not in ys:
                continue
            real = forward_cash(ys, t)
            if real is None:
                continue
            try:
                cur = engine(roic0, g0, w)
                a1 = engine(min(iroic, 0.40, roic0), g0, w)
                a0 = engine(roic0, 0.0, w)
            except ValuationError:
                continue
            def pred(res):
                eps, pay = res.eps_path[:5], res.payout_path[:5]
                return dict(ret=1 - sum(e * p for e, p in zip(eps, pay)) / sum(eps), cagr=eps[4] ** (1 / 5) - 1,
                            fcf=sum(e * p for e, p in zip(eps, pay)))
            recs.append(dict(code=code, year=t, floored=floored(ys[t]), roic0=roic0, g0=g0, rr=rr, real=real,
                             cur=pred(cur), a1=pred(a1), a0=pred(a0)))
    groups = {'触下限': [x for x in recs if x['floored']], '未触下限': [x for x in recs if not x['floored']]}
    groups['未触下限·ROIC0>40%'] = [x for x in recs if not x['floored'] and x['roic0'] > 0.40]
    summary = {}
    out('| 组 | n（公司） | 求 g0 所用再投资率 | 实际再投资占比 | 引擎留存 现行／A1 | g0 | 实际 NOPAT 年化 | 引擎增长 现行／A1／A0 | 实际自由现金÷NOPAT_t | 引擎自由现金 现行／A1／A0 |')
    out('| --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | --- |')
    for name, xs in groups.items():
        if not xs:
            continue
        s = dict(n=len(xs), companies=len({x['code'] for x in xs}),
                 rr=med(x['rr'] for x in xs), real_reinv=med(x['real']['reinv_share'] for x in xs),
                 ret_cur=med(x['cur']['ret'] for x in xs), ret_a1=med(x['a1']['ret'] for x in xs),
                 g0=med(x['g0'] for x in xs), real_cagr=med(x['real']['cagr'] for x in xs),
                 cagr_cur=med(x['cur']['cagr'] for x in xs), cagr_a1=med(x['a1']['cagr'] for x in xs), cagr_a0=0.0,
                 real_fcf=med(x['real']['fcf'] for x in xs), fcf_cur=med(x['cur']['fcf'] for x in xs),
                 fcf_a1=med(x['a1']['fcf'] for x in xs), fcf_a0=med(x['a0']['fcf'] for x in xs))
        # 自由现金误差：预测 − 实际（NOPAT_t 倍数），中位与 |误差| 中位
        for arm in ('cur', 'a1', 'a0'):
            errs = [x[arm]['fcf'] - x['real']['fcf'] for x in xs]
            s[f'fcf_bias_{arm}'], s[f'fcf_abs_{arm}'] = med(errs), med(abs(e) for e in errs)
            s[f'reinv_abs_{arm}'] = med(abs(x[arm]['ret'] - x['real']['reinv_share']) for x in xs)
        summary[name] = s
        out(f"| {name} | {s['n']}（{s['companies']}） | {s['rr']:.0%} | {s['real_reinv']:.0%} | {s['ret_cur']:.0%}／{s['ret_a1']:.0%} "
            f"| {s['g0']:.1%} | {s['real_cagr']:.1%} | {s['cagr_cur']:.1%}／{s['cagr_a1']:.1%}／0 | {s['real_fcf']:.2f} "
            f"| {s['fcf_cur']:.2f}／{s['fcf_a1']:.2f}／{s['fcf_a0']:.2f} |")
    out()
    out('自由现金误差（引擎 − 实际，NOPAT_t 倍数，5 年合计）：')
    for name, s in summary.items():
        out(f"- {name}：偏差中位 现行 {s['fcf_bias_cur']:+.2f}／A1 {s['fcf_bias_a1']:+.2f}／A0 {s['fcf_bias_a0']:+.2f}；"
            f"|误差| 中位 {s['fcf_abs_cur']:.2f}／{s['fcf_abs_a1']:.2f}／{s['fcf_abs_a0']:.2f}；"
            f"留存 |误差| 中位 现行 {s['reinv_abs_cur']:.0%}／A1 {s['reinv_abs_a1']:.0%}")
    fl = groups['触下限']
    out(f"- 触下限样本：{', '.join(sorted({x['code'] + ':' + str(x['year']) for x in fl}))}")
    m1b(ann)
    RESULT['M1'] = dict(summary=summary, floored_rows=[dict(code=x['code'], year=x['year'], g0=x['g0'], rr=x['rr'],
                                                            real=x['real'], cur=x['cur'], a1=x['a1']) for x in fl])
    out()


def m1b(ann):
    rows = []
    with (ROOT / 'data/processed/roic_bands.csv').open(encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if r['status'] != 'ok' or r['roic_path'] != 'growth' or r['roic_g_source'] != 'capital':
                continue
            g0, roic0, w, iroic, rr, d = (fnum(r[k]) for k in ('g0', 'roic0', 'wacc', 'incremental_roic', 'reinvestment_rate', 'growth_damp'))
            code, yr = r['security_code'], int(r['report_date'][:4])
            annual_row = r['report_date'].endswith('-12-31')
            t = yr if annual_row else yr - 1
            ys = ann.get(code)
            if not g0 or None in (roic0, w, rr, d) or not ys or t not in ys:
                continue
            a, b = ys.get(t), ys.get(t + 5)
            if not b or a.nopat is None or b.nopat is None or a.nopat <= 0 or b.nopat <= 0:
                continue
            res, damp = engine(roic0, g0, w), engine(roic0, g0 * d, w)
            eps, pay = res.eps_path[:5], res.payout_path[:5]
            rec = dict(annual=annual_row, g0=g0, d=d, real=(b.nopat / a.nopat) ** 0.2 - 1, pred=eps[4] ** 0.2 - 1,
                       pred_damp=damp.eps_path[4] ** 0.2 - 1)
            if annual_row:
                win = [ys.get(t - i) for i in range(5)]
                cash = forward_cash(ys, t)
                if cash and all(y is not None and y.nopat is not None for y in win) and iroic is not None:
                    ret = 1 - sum(e * p for e, p in zip(eps, pay)) / sum(eps)
                    rec.update(capped=iroic > 0.40, lowbase=0 < win[4].nopat < 0.5 * statistics.median(y.nopat for y in win[:4]),
                               rr=min(rr, 1.0), ret=ret, real_reinv=cash['reinv_share'], real_fcf=cash['fcf'],
                               fcf=sum(e * p for e, p in zip(eps, pay)), fcf_a1p=sum(eps) * (1 - max(ret, min(rr, 1.0))))
            rows.append(rec)
    ann_rows = [x for x in rows if x['annual'] and 'rr' in x]
    res = {}
    out('M1b 全部资本腿增长年报行：实际 5 年 NOPAT 年化 vs 引擎')
    out('| 组 | n | g0 | 引擎 5 年 | 实际 5 年 | 实际低于引擎 |')
    out('| --- | ---: | ---: | ---: | ---: | ---: |')
    groups = [(f'g0 {lo:.0%}～{hi:.0%}', lambda x, lo=lo, hi=hi: lo < x['g0'] <= hi) for lo, hi in ((0, .05), (.05, .10), (.10, .15), (.15, .20), (.20, 1))]
    groups += [('增量 ROIC 封顶且 g0 > 15%', lambda x: x['capped'] and x['g0'] > 0.15),
               ('低基数且 g0 > 15%', lambda x: x['lowbase'] and x['g0'] > 0.15)]
    for name, cond in groups:
        xs = [x for x in ann_rows if cond(x)]
        s = res[name] = dict(n=len(xs), g0=med(x['g0'] for x in xs), pred=med(x['pred'] for x in xs), real=med(x['real'] for x in xs),
                             below=sum(1 for x in xs if x['real'] < x['pred']) / len(xs))
        out(f"| {name} | {s['n']} | {s['g0']:.1%} | {s['pred']:.1%} | {s['real']:.1%} | {s['below']:.0%} |")
    out()
    out("再投资率与引擎留存之差（A1' = 前 5 年留存取两者较大、增长不变）：")
    out("| 再投资率 − 引擎留存 | n | 再投资率 | 引擎留存 | 实际再投资 | 引擎 5 年增长 | 实际 | 自由现金 实际／引擎／A1' | |误差| 引擎／A1' |")
    out('| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |')
    for lo, hi, name in ((-9, -0.2, '< −20pp'), (-0.2, 0.2, '±20pp'), (0.2, 9, '> +20pp')):
        xs = [x for x in ann_rows if lo <= x['rr'] - x['ret'] < hi]
        s = res[f'gap {name}'] = dict(n=len(xs), rr=med(x['rr'] for x in xs), ret=med(x['ret'] for x in xs),
                                      real_reinv=med(x['real_reinv'] for x in xs), pred=med(x['pred'] for x in xs),
                                      real=med(x['real'] for x in xs), real_fcf=med(x['real_fcf'] for x in xs),
                                      fcf=med(x['fcf'] for x in xs), fcf_a1p=med(x['fcf_a1p'] for x in xs),
                                      abs_cur=med(abs(x['fcf'] - x['real_fcf']) for x in xs),
                                      abs_a1p=med(abs(x['fcf_a1p'] - x['real_fcf']) for x in xs))
        out(f"| {name} | {s['n']} | {s['rr']:.0%} | {s['ret']:.0%} | {s['real_reinv']:.0%} | {s['pred']:.1%} | {s['real']:.1%} "
            f"| {s['real_fcf']:.2f}／{s['fcf']:.2f}／{s['fcf_a1p']:.2f} | {s['abs_cur']:.2f}／{s['abs_a1p']:.2f} |")
    out()
    out('M1c 资本腿乘增速腿折减 d：引擎 5 年增长 现行／折减 vs 实际（偏差 = 引擎 − 实际）')
    out('| 行 | d | n | 实际 | 引擎 现行／折减 | 偏差 现行／折减 | |误差| 现行／折减 |')
    out('| --- | --- | ---: | ---: | --- | --- | --- |')
    for annual_row in (True, False):
        for lo, hi, name in ((0.95, 9, '≥ 0.95'), (0.85, 0.95, '0.85～0.95'), (0.7, 0.85, '0.70～0.85'), (0, 0.7, '< 0.70')):
            xs = [x for x in rows if x['annual'] == annual_row and lo <= x['d'] < hi]
            if not xs:
                continue
            s = res[f"damp {'annual' if annual_row else 'quarter'} {name}"] = dict(
                n=len(xs), real=med(x['real'] for x in xs), pred=med(x['pred'] for x in xs), pred_damp=med(x['pred_damp'] for x in xs),
                bias=med(x['pred'] - x['real'] for x in xs), bias_damp=med(x['pred_damp'] - x['real'] for x in xs),
                abs=med(abs(x['pred'] - x['real']) for x in xs), abs_damp=med(abs(x['pred_damp'] - x['real']) for x in xs))
            out(f"| {'年报' if annual_row else '季报'} | {name} | {s['n']} | {s['real']:.1%} | {s['pred']:.1%}／{s['pred_damp']:.1%} "
                f"| {s['bias']:+.1%}／{s['bias_damp']:+.1%} | {s['abs']:.1%}／{s['abs_damp']:.1%} |")
    RESULT['M1b'] = res
    out()


def m2(ann):
    out('## M2 负营运资本（垫款）的持续性：原投入资本 < 0.1 × 总权益的年报行')
    rows = []
    for code, ys in ann.items():
        for t, y in ys.items():
            if not floored(y) or y.working_capital is None or y.working_capital >= 0 or not y.revenue:
                continue
            rec = dict(code=code, year=t, float0=-y.working_capital, rev0=y.revenue)
            for h in (3, 5):
                z = ys.get(t + h)
                if z is None or z.working_capital is None or not z.revenue:
                    continue
                rec[f'float{h}'] = -z.working_capital / rec['float0']
                rec[f'rev{h}'] = z.revenue / rec['rev0']
                rec[f'xcash{h}'] = (z.excess_cash / y.excess_cash) if y.excess_cash > 0 else None
            rows.append(rec)
    res = {}
    for h in (3, 5):
        xs = [r for r in rows if f'float{h}' in r]
        shrink = [r for r in xs if r[f'float{h}'] < 0.75]
        res[h] = dict(n=len(xs), companies=len({r['code'] for r in xs}), float_ratio=med(r[f'float{h}'] for r in xs),
                      rev_ratio=med(r[f'rev{h}'] for r in xs), shrink_share=len(shrink) / len(xs) if xs else None,
                      shrink_rev_ratio=med(r[f'rev{h}'] for r in shrink),
                      rev_down_shrink_share=(sum(1 for r in xs if r[f'rev{h}'] < 0.9 and r[f'float{h}'] < 0.75)
                                             / max(1, sum(1 for r in xs if r[f'rev{h}'] < 0.9))),
                      xcash_ratio=med(r.get(f'xcash{h}') for r in xs))
        s = res[h]
        out(f"- {h} 年后：n {s['n']}（{s['companies']} 家）；垫款倍数中位 {s['float_ratio']:.2f}、营收倍数中位 {s['rev_ratio']:.2f}；"
            f"垫款收缩 >25% 占 {s['shrink_share']:.0%}（这些行营收倍数中位 {s['shrink_rev_ratio']:.2f}）；"
            f"营收下降 >10% 的行中垫款收缩 >25% 占 {s['rev_down_shrink_share']:.0%}；超额现金倍数中位 {s['xcash_ratio']:.2f}")
    RESULT['M2'] = res
    out()


def m3(ann):
    out('## M3 λ = 0 的锚：三年中位 vs 当期（比率 = NOPAT ÷ 母公司权益）')
    ratio = {code: {t: y.nopat / y.parent_equity for t, y in ys.items()
                    if y.nopat is not None and y.parent_equity and y.parent_equity > 0} for code, ys in ann.items()}
    equity = {code: {t: y.parent_equity for t, y in ys.items() if y.parent_equity and y.parent_equity > 0}
              for code, ys in ann.items()}
    nopat = {code: {t: y.nopat for t, y in ys.items() if y.nopat is not None} for code, ys in ann.items()}

    def state(code, t):
        """年报 t 的 λ、三年中位、峰谷权重（§6.5.1 年报行口径）。"""
        rs = ratio[code]
        if not all(t - i in rs for i in range(3)):
            return None
        last3 = [rs[t - 2], rs[t - 1], rs[t]]
        lam = sum(1 for i in (1, 2) if last3[i] > last3[i - 1]) / 2
        hist = [rs[y] for y in range(t - 9, t + 1) if y in rs]
        med10 = statistics.median(hist) if len(hist) >= 4 else None
        w = v = 0.0
        if med10 and med10 > 0 and rs[t] > 0:
            s = rs[t] / med10
            w, v = min(1, max(0, (s - 1.3) / 0.6)), min(1, max(0, (1 / s - 1.3) / 0.6))
        return dict(lam=lam, base3=statistics.median(last3), cur=rs[t], guard=max(w, v))

    def realized(code, start, h=3):
        rs = ratio[code]
        f = [rs.get(start + i) for i in range(h)]
        if any(x is None for x in f):
            return None, None
        lv = [nopat[code].get(start + i) for i in range(h)]
        base_eq = equity[code].get(start - 1)
        level = statistics.mean(lv) / base_eq if base_eq and all(x is not None for x in lv) else None
        return statistics.mean(f), level

    def score(recs, label, key):
        out(f'### {label}')
        out('| 当期 ÷ 三年中位 | n | 实际 ÷ 三年中位（中位） | ln 误差 三年中位 | ln 误差 当期 | ln 误差 均值 | |误差| 三年中位／当期／均值 |')
        out('| --- | ---: | ---: | ---: | ---: | ---: | --- |')
        res = {}
        for lo, hi, name in ((0.95, 9, '≥ 0.95'), (0.85, 0.95, '0.85～0.95'), (0.70, 0.85, '0.70～0.85'), (0, 0.70, '< 0.70'), (0, 9, '全部')):
            xs = [r for r in recs if lo <= r['cur'] / r['base3'] < hi and r[key] and r[key] > 0 and r['cur'] > 0]
            if not xs:
                continue
            e = {a: [math.log(r[a] / r[key]) for r in xs] for a in ('base3', 'cur', 'mid')}
            res[name] = dict(n=len(xs), real_over_base=med(r[key] / r['base3'] for r in xs),
                             **{f'bias_{a}': med(v) for a, v in e.items()}, **{f'abs_{a}': med(abs(x) for x in v) for a, v in e.items()})
            s = res[name]
            out(f"| {name} | {s['n']} | {s['real_over_base']:.2f} | {s['bias_base3']:+.3f} | {s['bias_cur']:+.3f} | {s['bias_mid']:+.3f} "
                f"| {s['abs_base3']:.3f}／{s['abs_cur']:.3f}／{s['abs_mid']:.3f} |")
        out()
        return res

    annual_recs = []
    for code in ratio:
        for t in ratio[code]:
            st = state(code, t)
            if not st or st['lam'] > 0 or st['guard'] > 0 or st['base3'] <= 0:
                continue
            real, level = realized(code, t + 1)
            annual_recs.append(dict(code=code, year=t, base3=st['base3'], cur=st['cur'], mid=(st['base3'] + st['cur']) / 2,
                                    real=real, level=level))
    q_recs = []
    with (ROOT / 'data/processed/roic_bands.csv').open(encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            if r['status'] != 'ok' or r['report_date'].endswith('-12-31') or r['roic_nopat_mode'] != 'median3':
                continue
            code, yr, f = r['security_code'], int(r['report_date'][:4]), fnum(r['ttm_factor'])
            if code not in ratio or f is None or f == 1.0:
                continue
            st = state(code, yr - 1)
            if not st or st['lam'] > 0 or st['base3'] <= 0:
                continue
            cur = st['cur'] * f
            real, level = realized(code, yr)
            q_recs.append(dict(code=code, year=yr, period=r['report_date'], base3=st['base3'], cur=cur,
                               mid=(st['base3'] + cur) / 2, real=real, level=level))
    RESULT['M3'] = {'annual_real': score(annual_recs, '年报行（λ = 0、无守卫），实际 = t+1～t+3 比率均值', 'real'),
                    'annual_level': score(annual_recs, '年报行，第二口径 = t+1～t+3 NOPAT 均值 ÷ t 年权益', 'level'),
                    'quarter_real': score(q_recs, '季报行（生产 median3），当期 = 年报比率 × TTM 因子，实际 = 报告年起 3 年比率均值', 'real'),
                    'quarter_level': score(q_recs, '季报行，第二口径', 'level')}


def main():
    stmts = roic_inputs.load_statements(None, roic_inputs.STMT_DIR, ic_floor=FLOOR, caliber='nonop', notice_cap=True)
    ann = annual(stmts)
    m1(ann)
    m2(ann)
    m3(ann)
    (EXP / 'mechanism.json').write_text(json.dumps(RESULT, ensure_ascii=False, indent=1, default=str))
    (EXP / 'mechanism.txt').write_text('\n'.join(LINES) + '\n')


if __name__ == '__main__':
    main()

"""OI-233 策略对比（用户 2026-09-29：「具体对比这几个策略的效果，说明各个策略的主要差异」）。

只读本批已有产物（summary_rows.csv、nav/、trades/、stats/），不重跑引擎：
收益与回撤水平、逐起点、逐年、交易行为与资金占用、个股归因（14 起点平均）、持有期与锁仓诊断。

    python3 compare.py     # → comparison.json、comparison.md
"""
import csv
import glob
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402
sys.path.insert(0, str(EXP))
from run import STATES  # noqa: E402

ALL = ('BASE', 'ZH070', 'ZH085', 'ZHL', 'NS', 'BT2', 'BT3', 'BT5', 'BTNS')
MAIN = ('BASE', 'NS', 'BT3', 'BTNS')
STARTS = sw.DEFAULT_STARTS
CREDIT = 0.666                                   # 授信比例（§10.2），只用于判「负债已到授信线」
INDEX = ROOT / 'data/raw/ohlcv/INDEX_000300.csv'
NAMES = (ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv', ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv')
DETAIL_YEARS = range(2011, 2027)
SNAP_START = sw.EX5_ANCHOR_START                 # 年末持仓快照只看锚点起点（与 case_*.md 同一起点）


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_summary():
    out = {}
    for r in csv.DictReader((EXP / 'summary_rows.csv').open(encoding='utf-8')):
        out[(r['arm'], r['group'], r['start'])] = r
    return out


def tag(arm, start, group='full'):
    s = start.replace('-', '')
    return f'{arm}full{s}' if group == 'full' else f'{arm}A{s}ex5'


def load_nav(arm, start, group='full'):
    rows = []
    with (EXP / 'nav' / f'{tag(arm, start, group)}.csv').open(encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append((r['date'], float(r['net_equity']), float(r['cash']), int(r['positions']), float(r['debt']),
                         num(r.get('top1_weight')) or 0.0))
    return rows


def levels(summary):
    """14 起点水平（中位）与对 BASE 的逐起点配对差（中位、胜场）。"""
    keys = (('年化', 'full', '年化'), ('年化_A', 'A', '年化'), ('最大回撤', 'full', '最大回撤'), ('年化波动', 'full', '年化波动'),
            ('Sharpe', 'full', 'Sharpe'), ('Calmar', 'full', 'Calmar'), ('滚5年化中位', 'full', '滚动5年年化中位'),
            ('滚5年化P25', 'full', '滚动5年年化P25'), ('滚5回撤中位', 'full', '滚动5年回撤中位'), ('逐年最差', 'full', '逐年最差'))
    lower_better = {'最大回撤', '年化波动', '滚5回撤中位'}
    out = {}
    for arm in ALL:
        out[arm] = {}
        for name, group, col in keys:
            vals = {s: num(summary[(arm, group, s)][col]) for s in STARTS}
            base = {s: num(summary[('BASE', group, s)][col]) for s in STARTS}
            d = [vals[s] - base[s] for s in STARTS]
            better = sum((x < 0) if name in lower_better else (x > 0) for x in d)
            out[arm][name] = dict(median=med(vals.values()), worst=(max if name in lower_better else min)(vals.values()),
                                  d_median=med(d), better=better, per_start=vals)
    return out


def calendar(arms):
    """逐年收益：只取整年在场的起点；年收益 = 年末净资产 ÷ 上年末 − 1；2026 为截至末次净值日。"""
    idx = {}
    with INDEX.open(encoding='utf-8') as f:
        for r in csv.DictReader(f):
            idx[r['date']] = float(r['close'])
    idx_days = sorted(idx)

    def year_end(days, y):
        cands = [d for d in days if d[:4] == str(y)]
        return cands[-1] if cands else None
    per = defaultdict(dict)          # (arm, year) → {start: ret}
    dd = defaultdict(dict)           # (arm, year) → {start: 年内最大回撤}
    for arm in arms:
        for s in STARTS:
            nav = load_nav(arm, s)
            eq = {d: e for d, e, *_ in nav}
            days = [d for d, *_ in nav]
            for y in range(2010, 2027):
                prev, cur = year_end(days, y - 1), year_end(days, y)
                if not prev or not cur or prev < s:
                    continue
                per[(arm, y)][s] = eq[cur] / eq[prev] - 1
                peak, worst = eq[prev], 0.0
                for d in days:
                    if prev < d <= cur:
                        peak = max(peak, eq[d])
                        worst = max(worst, 1 - eq[d] / peak)
                dd[(arm, y)][s] = worst
    out = {}
    for y in range(2010, 2027):
        p, c = year_end(idx_days, y - 1), year_end(idx_days, y)
        row = dict(index=(idx[c] / idx[p] - 1) if p and c else None, n=len(per.get(('BASE', y), {})))
        for arm in arms:
            vals = per.get((arm, y), {})
            if not vals:
                continue
            base = per[('BASE', y)]
            d = [vals[s] - base[s] for s in vals]
            row[arm] = dict(median=med(vals.values()), d_median=med(d), better=sum(x > 0 for x in d), dd_median=med(dd[(arm, y)].values()))
        out[y] = row
    return out


def behaviour(summary):
    """交易行为与资金占用：summary 字段取 14 起点中位；stats 计数；NAV 派生的只数、负债到线天数。"""
    cols = ('买入笔数', '卖出笔数', '周期数', '平均持有天数', '胜率', '盈亏比', '年均换手', '手续费占初始本金', '平均仓位',
            '持仓数中位', '单票权重中位', '前三权重中位', '单票超60%天数占比', '前五赢家占正贡献')
    out = {}
    for arm in ALL:
        row = {c: med([num(summary[(arm, 'full', s)][c]) for s in STARTS]) for c in cols}
        st = [json.loads((EXP / 'stats' / f'{tag(arm, s)}.json').read_text()) for s in STARTS]
        navs = [load_nav(arm, s) for s in STARTS]
        row['止损次数'] = med([x.get('止损触发·confirmed', 0) for x in st])
        row['换仓卖出'] = med([x.get('换仓·减一档', 0) + x.get('换仓·整仓卖出', 0) for x in st])
        row['涨幅减持'] = med([x.get('涨幅≥110%·减一档', 0) for x in st])
        row['股债减仓笔数'] = med([x.get('股债·主动减仓笔数', 0) for x in st])
        row['超额授信无新增买入日占比'] = med([x.get('超额授信·当日无新增买入', 0) / max(1, len(n)) for x, n in zip(st, navs)])
        row['买不足一手跳过（候选日）'] = med([x.get('买不足一手·跳过', 0) for x in st])
        row['负债到线日占比'] = med([sum(debt >= CREDIT * e - 1 for _, e, _, _, debt, _ in n if e > 0) / len(n) for n in navs])
        row['持仓≤3只日占比'] = med([sum(0 < p <= 3 for _, _, _, p, _, _ in n) / len(n) for n in navs])
        row['空仓日占比'] = med([sum(p == 0 for _, _, _, p, _, _ in n) / len(n) for n in navs])
        out[arm] = row
    return out


def trades(arm):
    out = {}
    for s in STARTS:
        with (EXP / 'trades' / f'{tag(arm, s)}_trades.csv').open(newline='', encoding='utf-8') as f:
            out[s] = list(csv.DictReader(f))
    return out


def names():
    out = {}
    for path in NAMES:
        if path.exists():
            for r in csv.DictReader(path.open(encoding='utf-8')):
                if r.get('security_code') and r.get('security_name'):
                    out[r['security_code'].zfill(6)] = r['security_name']
    for p in glob.glob(str(EXP / 'ledgers' / 'ledger_*.csv')):
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r.get('security_name'):
                out.setdefault(r['security_code'].zfill(6), r['security_name'])
    return out


def attribution(all_trades):
    """个股 contrib（盈亏 ÷ 前一日净资产），每起点按票合计，14 起点平均（未持有记 0）；持有起点数。"""
    out = {}
    for arm, starts in all_trades.items():
        acc, held = defaultdict(float), defaultdict(int)
        for s, cycles in starts.items():
            per = defaultdict(float)
            for c in cycles:
                per[c['security_code'].zfill(6)] += float(c['contrib'] or 0)
            for code, v in per.items():
                acc[code] += v / len(STARTS)
                held[code] += 1
        out[arm] = dict(mean=dict(acc), held=dict(held))
    return out


def holding(all_trades):
    """持有期与锁仓：周期持有天数分布、长持亏损周期、周期内最大回撤，逐起点合计后取中位。"""
    out = {}
    for arm, starts in all_trades.items():
        per = defaultdict(list)
        pooled = []
        for s, cycles in starts.items():
            n = len(cycles)
            long_ = [c for c in cycles if int(c['holding_days'] or 0) >= 365]
            long_loss = [c for c in long_ if float(c['return_pct'] or 0) < 0]
            short_ = [c for c in cycles if int(c['holding_days'] or 0) <= 30]
            per['周期数'].append(n)
            per['≤30天周期占比'].append(len(short_) / n if n else None)
            per['≥1年周期占比'].append(len(long_) / n if n else None)
            per['≥1年周期contrib'].append(sum(float(c['contrib'] or 0) for c in long_))
            per['≥1年且亏损周期数'].append(len(long_loss))
            per['≥1年且亏损contrib'].append(sum(float(c['contrib'] or 0) for c in long_loss))
            per['≤30天周期contrib'].append(sum(float(c['contrib'] or 0) for c in short_))
            per['每周期买入笔数'].append(sum(int(c['buys'] or 0) for c in cycles) / n if n else None)
            pooled += cycles
        row = {k: med(v) for k, v in per.items()}
        dd = [float(c['max_drawdown_in_cycle'] or 0) for c in pooled if int(c['holding_days'] or 0) >= 365]
        row['≥1年周期内回撤中位'] = med(dd)
        row['≥1年周期内回撤≥40%占比'] = sum(x >= 0.4 for x in dd) / len(dd) if dd else None
        out[arm] = row
    return out


def detail():
    """detail.py 产物：逐年个股 contrib 差（整年在场的起点平均）与锚点起点年末持仓。无产物时跳过。"""
    paths = {(a, s): EXP / 'detail' / f"{tag(a, s)}.json" for a in MAIN for s in STARTS}
    if not all(p.exists() for p in paths.values()):
        return None
    pv_month = {}                        # (代码, 月) → 当月最后一个持仓侧 P/V（无估值记 None）
    with (STATES / 'a_share_daily_states_hold.csv').open(newline='', encoding='utf-8') as f:
        r = csv.reader(f)
        h = next(r)
        ic, idt, ipv = h.index('security_code'), h.index('date'), h.index('valuation_ratio')
        for row in r:
            v = num(row[ipv])
            pv_month[(row[ic], row[idt][:7])] = v if v and v > 0 else None
    years = defaultdict(dict)            # (arm, start) → {year: {code: contrib}}
    snap, where = {}, defaultdict(lambda: defaultdict(list))
    for (a, s), p in paths.items():
        d = json.loads(p.read_text())
        per = defaultdict(dict)
        for key, v in d['contrib_year'].items():
            code, y = key.split('|')
            per[int(y)][code] = v
        years[(a, s)] = per
        if s == SNAP_START:
            snap[a] = {m: w for m, w in d['weights_month'].items() if m.endswith('-12') or m == max(d['weights_month'])}
        acc, n_month = defaultdict(float), 0
        for m, w in d['weights_month'].items():
            gross = sum(w.values())
            if gross <= 0:
                continue
            n_month += 1
            for code, x in w.items():
                acc[pv_bucket(pv_month.get((code, m)))] += x / gross
        for k in PV_BUCKETS:
            where[a][k].append(acc[k] / n_month if n_month else None)
    by_year = {}
    for y in DETAIL_YEARS:
        active = [s for s in STARTS if int(s[:4]) <= y - 1]      # 与 calendar() 同：整年在场
        if not active:
            continue
        row = dict(n=len(active))
        for a in MAIN[1:]:
            diff = defaultdict(float)
            for s in active:
                for code in set(years[(a, s)].get(y, {})) | set(years[('BASE', s)].get(y, {})):
                    diff[code] += (years[(a, s)].get(y, {}).get(code, 0.0) - years[('BASE', s)].get(y, {}).get(code, 0.0)) / len(active)
            ranked = sorted(diff.items(), key=lambda kv: kv[1])
            row[a] = dict(total=sum(diff.values()), top=ranked[::-1][:3], bottom=ranked[:3])
        by_year[y] = row
    return dict(by_year=by_year, snapshots=snap, where={a: {k: med(v) for k, v in where[a].items()} for a in MAIN})


PV_BUCKETS = ('≤0.70', '0.70～1.0034', '1.0034～1.30', '>1.30', '无估值')


def pv_bucket(v):
    if v is None:
        return '无估值'
    return '≤0.70' if v <= 0.70 else '0.70～1.0034' if v <= 1.0034 else '1.0034～1.30' if v <= 1.30 else '>1.30'


def main():
    summary = load_summary()
    all_trades = {a: trades(a) for a in ALL}
    res = dict(levels=levels(summary), calendar=calendar(MAIN), behaviour=behaviour(summary),
               attribution=attribution(all_trades), holding=holding(all_trades), detail=detail())
    (EXP / 'comparison.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    write_md(res, names())


def write_md(res, nm):
    pct = lambda x, d=1: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None else f'{x * 100:+.{d}f}'
    lv, bh, hd, at, cal = res['levels'], res['behaviour'], res['holding'], res['attribution'], res['calendar']
    n = len(STARTS)
    out = ['# OI-233 策略对比（v4.221 状态，买入线 1.0034，14 起点，只读本批产物）', '',
           '水平取 14 起点中位；Δ 为对 `BASE` 的逐起点配对差中位（pp），括号内为 14 个起点中优于 `BASE` 的个数（回撤、波动以更小为优）。'
           '年化与回撤是参考读数，不作取舍依据。', '',
           '## 一、收益与回撤', '',
           '| 臂 | 年化 | Δ年化 | 年化（A） | Δ年化（A） | 最大回撤 | Δ回撤 | 最深回撤 | 年化波动 | Sharpe | Calmar | 滚5年化中位 | 滚5 P25 | 逐年最差（中位） |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in ALL:
        L = lv[arm]
        dl = lambda k: '—' if arm == 'BASE' else f"{pp(L[k]['d_median'])}（{L[k]['better']}/{n}）"
        out.append(f"| {arm} | {pct(L['年化']['median'])} | {dl('年化')} | {pct(L['年化_A']['median'])} | {dl('年化_A')} | "
                   f"{pct(L['最大回撤']['median'])} | {dl('最大回撤')} | {pct(L['最大回撤']['worst'])} | {pct(L['年化波动']['median'])} | "
                   f"{L['Sharpe']['median']:.2f} | {L['Calmar']['median']:.2f} | {pct(L['滚5年化中位']['median'])} | {pct(L['滚5年化P25']['median'])} | "
                   f"{pct(L['逐年最差']['median'])} |")
    out += ['', '## 二、逐起点年化／最大回撤（全样本）', '', '| 起点 | ' + ' | '.join(MAIN) + ' |', '| --- |' + ' ---: |' * len(MAIN)]
    for s in STARTS:
        out.append(f'| {s} | ' + ' | '.join(f"{pct(lv[a]['年化']['per_start'][s])}／{pct(lv[a]['最大回撤']['per_start'][s])}" for a in MAIN) + ' |')
    out += ['', '## 三、逐年收益（整年在场的起点中位；Δ 对 BASE 配对中位，括号为优于 BASE 的起点数）', '',
            '| 年 | 起点数 | 沪深300（价格） | BASE | NS Δ | BT3 Δ | BTNS Δ | 年内回撤中位 BASE／NS／BT3／BTNS |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for y, row in cal.items():
        if 'BASE' not in row:
            continue
        cell = lambda a: f"{pp(row[a]['d_median'], 1)}（{row[a]['better']}/{row['n']}）"
        yl = f'{y}（至 8 月）' if y == 2026 else str(y)
        out.append(f"| {yl} | {row['n']} | {pct(row['index'])} | {pct(row['BASE']['median'])} | {cell('NS')} | {cell('BT3')} | {cell('BTNS')} | "
                   + '／'.join(pct(row[a]['dd_median'], 0) for a in MAIN) + ' |')
    out += ['', '## 四、交易行为与资金占用（14 起点中位）', '']
    cols = ('买入笔数', '卖出笔数', '周期数', '平均持有天数', '胜率', '盈亏比', '止损次数', '换仓卖出', '涨幅减持', '股债减仓笔数',
            '年均换手', '手续费占初始本金', '平均仓位', '持仓数中位', '持仓≤3只日占比', '单票权重中位', '前三权重中位', '单票超60%天数占比',
            '前五赢家占正贡献', '负债到线日占比', '超额授信无新增买入日占比', '买不足一手跳过（候选日）')
    pcts = {'胜率', '年均换手', '手续费占初始本金', '平均仓位', '持仓≤3只日占比', '单票权重中位', '前三权重中位', '单票超60%天数占比',
            '前五赢家占正贡献', '负债到线日占比', '超额授信无新增买入日占比'}
    out += ['| 项 | ' + ' | '.join(ALL) + ' |', '| --- |' + ' ---: |' * len(ALL)]
    for c in cols:
        fmt = (lambda x: pct(x, 0)) if c in pcts and c != '年均换手' else (lambda x: '—' if x is None else f'{x:.2f}' if c in ('年均换手', '盈亏比') else f'{x:.0f}')
        out.append(f'| {c} | ' + ' | '.join(fmt(bh[a][c]) for a in ALL) + ' |')
    out += ['', '## 五、持有期与锁仓（逐起点合计后取中位；contrib 为 pp）', '']
    hcols = ('周期数', '≤30天周期占比', '≤30天周期contrib', '≥1年周期占比', '≥1年周期contrib', '≥1年且亏损周期数', '≥1年且亏损contrib',
             '≥1年周期内回撤中位', '≥1年周期内回撤≥40%占比', '每周期买入笔数')
    out += ['| 项 | ' + ' | '.join(ALL) + ' |', '| --- |' + ' ---: |' * len(ALL)]
    for c in hcols:
        fmt = (lambda x: pp(x, 1)) if 'contrib' in c else (lambda x: pct(x, 0)) if ('占比' in c or '回撤' in c) else (lambda x: '—' if x is None else f'{x:.1f}')
        out.append(f'| {c} | ' + ' | '.join(fmt(hd[a][c]) for a in ALL) + ' |')
    out += ['', '## 六、个股归因：对比两臂差异最大的股票（14 起点平均 contrib，pp；括号为持有过的起点数）', '']
    for a, b in (('NS', 'BASE'), ('BT3', 'BASE'), ('BTNS', 'BASE'), ('BTNS', 'BT3'), ('BTNS', 'NS')):
        ma, mb = at[a]['mean'], at[b]['mean']
        codes = set(ma) | set(mb)
        diff = sorted(((ma.get(c, 0) - mb.get(c, 0), c) for c in codes), reverse=True)
        total = sum(ma.values()) - sum(mb.values())
        out += [f'### {a} 对 {b}：合计 {pp(total, 1)}', '', f'| 股票 | Δ | {a} | {b} |', '| --- | ---: | ---: | ---: |']
        for d, c in diff[:8] + diff[-8:]:
            out.append(f"| {nm.get(c, '')}（{c}） | {pp(d, 1)} | {pp(ma.get(c, 0), 1)}（{at[a]['held'].get(c, 0)}） | {pp(mb.get(c, 0), 1)}（{at[b]['held'].get(c, 0)}） |")
        out.append('')
    det = res.get('detail')
    if det:
        nm_ = lambda c: nm.get(c) or c
        cell = lambda r: (f"{pp(r['total'], 1)}；" + '、'.join(f"{nm_(c)} {pp(v, 1)}" for c, v in r['top'] if v > 0.005)
                          + '／' + '、'.join(f"{nm_(c)} {pp(v, 1)}" for c, v in r['bottom'] if v < -0.005))
        out += ['## 七、逐年个股归因（对 BASE 的 contrib 差，整年在场的起点平均，pp；「；」后为拉高最多的三只／拖累最多的三只）', '',
                '逐日「盈亏 ÷ 前一日净资产」按年累计（`detail.py` 只记账补丁，期末资产逐位复现在册值），是算术累加，不等于第三节的复利年收益。', '',
                '| 年 | 起点数 | NS | BT3 | BTNS |', '| --- | ---: | --- | --- | --- |']
        for y, r in det['by_year'].items():
            yl = f'{y}（至 8 月）' if int(y) == 2026 else str(y)
            out.append(f"| {yl} | {r['n']} | {cell(r['NS'])} | {cell(r['BT3'])} | {cell(r['BTNS'])} |")
        out += ['', f'## 八、锚点起点（{SNAP_START}）年末持仓（持仓市值 ÷ 净资产，前四只）', '',
                '| 年末 | ' + ' | '.join(MAIN) + ' |', '| --- |' + ' --- |' * len(MAIN)]
        months = sorted(set().union(*(set(det['snapshots'][a]) for a in MAIN)))
        for m in months:
            cells = []
            for a in MAIN:
                w = det['snapshots'][a].get(m) or {}
                top = sorted(w.items(), key=lambda kv: -kv[1])[:4]
                cells.append(f"{pct(sum(w.values()), 0)}：" + '、'.join(f"{nm_(c)} {pct(v, 0)}" for c, v in top) if w else '空仓')
            out.append(f'| {m} | ' + ' | '.join(cells) + ' |')
        out += ['', '## 九、资金停在哪里：月末持仓按持仓侧 `P/V` 分档的市值占比（逐起点时间平均，14 起点中位）', '',
                '| 臂 | ' + ' | '.join(PV_BUCKETS) + ' |', '| --- |' + ' ---: |' * len(PV_BUCKETS)]
        for a in MAIN:
            out.append(f'| {a} | ' + ' | '.join(pct(det['where'][a][k], 0) for k in PV_BUCKETS) + ' |')
        out.append('')
    (EXP / 'comparison.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()

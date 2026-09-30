"""OI-249 读数（preregister.md「读数」1～5）。

公允性 λ 复用 OI-245 第二段的回归与判定（`../exp_oi245b_20260930/analyze2.py`：月份固定效应、按股票整簇自助 1000 次、90% 区间）；
每个候选各用种子 20260930 起一个随机数发生器。

    python3 analyze4.py      # → readings4.json、readings4.md
"""
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(EXP.parent / 'exp_oi245b_20260930'))
sys.path.insert(0, str(EXP))
import analyze2 as a2  # noqa: E402
from build import CASES, VARIANTS  # noqa: E402

NEW = [v for v in VARIANTS if v != 'ctrl']
LABEL = {'c1': 'C1 量驱动放宽', 'c1b': 'C1b 量驱动放宽（除商品定价型）', 'c2': 'C2 roic0 同口径', 'c12': 'C12 = C1 + C2'}
CASE_BANDS = {'300308': ['2024-06-30', '2024-09-30', '2024-12-31', '2025-03-31', '2025-06-30', '2025-12-31'],
              '300502': ['2024-12-31', '2025-03-31'], '300394': ['2024-12-31', '2025-03-31'],
              '002371': ['2023-12-31', '2024-12-31', '2025-12-31'], '300274': ['2022-12-31', '2023-12-31'],
              '300750': ['2019-06-30', '2022-12-31', '2023-12-31'], '002714': ['2020-12-31'], '002466': ['2022-12-31'],
              '002460': ['2022-12-31'], '000792': ['2022-12-31'], '601088': ['2011-12-31'], '002128': ['2011-12-31'],
              '600438': ['2023-12-31']}


def load():
    rows = []
    with (EXP / 'observations4.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            row = dict(code=r['code'], month=r['month'], pv=float(r['pv']), y=a2.fnum(r['f3']), w=float(r['w']), em=r['em2016'],
                       commodity=r['commodity'] == 'True', panel=r['panel'] == 'True')
            for v in NEW:
                row[v] = a2.fnum(r.get(f'pv_{v}'))
                row[f'w_{v}'] = a2.fnum(r.get(f'w_{v}'))
            rows.append(row)
    return [r for r in rows if r['panel'] and r['y'] is not None and a2.PV_RANGE[0] <= r['pv'] <= a2.PV_RANGE[1]]


def hits(rows):
    """C1 命中：对照 w > 0、C1 后 w = 0 的行，按年与 em2016 二级分类计；C1 与 C1b 之差（商品定价型）单列。"""
    c1 = [r for r in rows if r['w'] > 0 and r['w_c1'] == 0.0]
    c1b = [r for r in rows if r['w'] > 0 and r['w_c1b'] == 0.0]
    level2 = lambda em: '-'.join(em.split('-')[:2]) if em else '未登记'
    only_c1 = [r for r in c1 if not (r['w_c1b'] == 0.0)]
    return dict(c1_rows=len(c1), c1_codes=len({r['code'] for r in c1}), c1b_rows=len(c1b), c1b_codes=len({r['code'] for r in c1b}),
                guarded_rows=sum(r['w'] > 0 for r in rows),
                by_year=dict(sorted(Counter(r['month'][:4] for r in c1).items())),
                by_industry=Counter(level2(r['em']) for r in c1).most_common(),
                commodity_only=sorted({(r['code'], level2(r['em'])) for r in only_c1}),
                c1_codes_list=sorted({r['code'] for r in c1}))


def closes(code):
    path = ROOT / f'data/raw/ohlcv/{code}.csv'
    if not path.exists():
        return {}
    with path.open(newline='', encoding='utf-8') as f:
        return {r['date']: float(r['close']) for r in csv.DictReader(f)}


def cases(names):
    bands = {v: {} for v in VARIANTS}
    for v in VARIANTS:
        with (EXP / f'bands_{v}.csv').open(newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['security_code'] in CASE_BANDS and r['report_date'] in CASE_BANDS[r['security_code']]:
                    bands[v][(r['security_code'], r['report_date'])] = r
    out = []
    for code, dates in CASE_BANDS.items():
        cl = closes(code)
        for d in dates:
            ctrl = bands['ctrl'].get((code, d))
            if ctrl is None:
                out.append(dict(code=code, name=CASES.get(code, ''), report_date=d, note='未建带'))
                continue
            day = max((k for k in cl if k < ctrl['available_at']), default=None)
            px = cl.get(day) if day else None
            row = dict(code=code, name=CASES.get(code, ''), report_date=d, available_at=ctrl['available_at'], day=day, price=px,
                       w=a2.fnum(ctrl['peak_weight']), status=ctrl['status'])
            for v in VARIANTS:
                b = bands[v].get((code, d))
                val = a2.fnum(b['intrinsic_value']) if b and b['status'] == 'ok' else None
                row[f'v_{v}'] = val
                row[f'pv_{v}'] = px / val if px and val else None
            out.append(row)
    return out


def main():
    rows = load()
    res = dict(n=len(rows), codes=len({r['code'] for r in rows}), check=json.loads((EXP / 'observations4_check.json').read_text()),
               build=json.loads((EXP / 'build.json').read_text()))
    main_, periods, zone = {}, {}, {}
    for v in NEW:
        main_[v] = a2.strip(a2.fairness(rows, v, np.random.default_rng(a2.SEED)))
        periods[v] = {lab: a2.strip(a2.fairness(rows, v, np.random.default_rng(a2.SEED), a, b)) for lab, a, b in a2.PERIODS}
        zone[v] = a2.zone_share(rows, v)
    res.update(main=main_, periods=periods, zone=dict(ctrl=a2.zone_share(rows, 'pv'), **zone), hits=hits(rows), cases=cases(None))
    (EXP / 'readings4.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n', encoding='utf-8')
    write_md(res)


def write_md(res):
    f2 = lambda x, d=2: '—' if x is None else f'{x:.{d}f}'
    pct = lambda x, d=2: '—' if x is None else f'{x * 100:.{d}f}%'
    ci = lambda c: '［—］' if not c else f'［{c[0]:.2f}, {c[1]:.2f}］'
    out = [f"# OI-249 读数（面板在册、3 年、2007 年起；{res['n']} 行、{res['codes']} 只）", '',
           f"观测核对：{json.dumps({k: v for k, v in res['check'].items() if not isinstance(v, dict)}, ensure_ascii=False)}；"
           f"变动行 {json.dumps(res['check']['changed'], ensure_ascii=False)}；缺带 {json.dumps(res['check']['missing'], ensure_ascii=False)}。", '',
           '## 一、主读数（公允性 λ）', '', '| 候选 | λ | 90% 区间 | 判定 | 变动行 | 变动代码 | 平均 d | 买入区占比（对照 → 候选） |',
           '| --- | ---: | --- | --- | ---: | ---: | ---: | --- |']
    for v in NEW:
        m = res['main'][v]
        out.append(f"| {LABEL[v]} | {f2(m.get('lam'))} | {ci(m.get('lam_ci'))} | {m.get('verdict', '—')} | {m.get('moved')} | {m.get('moved_codes')} | "
                   f"{f2(m.get('mean_d'), 3)} | {pct(res['zone']['ctrl'])} → {pct(res['zone'][v])} |")
    out += ['', '## 二、分段', '', '| 候选 | ' + ' | '.join(lab for lab, *_ in a2.PERIODS) + ' |', '| --- |' + ' --- |' * len(a2.PERIODS)]
    for v in NEW:
        cells = []
        for lab, *_ in a2.PERIODS:
            p = res['periods'][v][lab]
            cells.append('样本不足' if p.get('skipped') else f"{f2(p.get('lam'))} {ci(p.get('lam_ci'))}（变动 {p.get('moved')}）")
        out.append(f"| {LABEL[v]} | " + ' | '.join(cells) + ' |')
    h = res['hits']
    out += ['', '## 三、C1 命中的行', '',
            f"对照峰守卫生效（w > 0）的行 {h['guarded_rows']}；C1 放宽 {h['c1_rows']} 行／{h['c1_codes']} 只，C1b 放宽 {h['c1b_rows']} 行／{h['c1b_codes']} 只。", '',
            '按年：' + '、'.join(f'{y} {n}' for y, n in h['by_year'].items()), '',
            '按 em2016 二级：' + '、'.join(f'{k} {n}' for k, n in h['by_industry']), '',
            '命中且属商品定价型（C1 有、C1b 无）：' + ('、'.join(f'{c}（{k}）' for c, k in h['commodity_only']) or '无'), '',
            '## 四、个案（带生效日收盘价）', '', '| 代码 | 名称 | 报告期 | 生效日 | 收盘 | 对照 w | V 对照 | C1 | C1b | C2 | C12 | `P/V` 对照 | C1 | C1b | C2 | C12 |',
            '| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for c in res['cases']:
        if c.get('note'):
            out.append(f"| {c['code']} | {c['name']} | {c['report_date']} | — | — | — | {c['note']} |" + ' |' * 9)
            continue
        vs = ' | '.join(f2(c[f'v_{v}']) for v in VARIANTS)
        pvs = ' | '.join(f2(c[f'pv_{v}']) for v in VARIANTS)
        out.append(f"| {c['code']} | {c['name']} | {c['report_date']} | {c['day']} | {f2(c['price'])} | {f2(c['w'])} | {vs} | {pvs} |")
    (EXP / 'readings4.md').write_text('\n'.join(out) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

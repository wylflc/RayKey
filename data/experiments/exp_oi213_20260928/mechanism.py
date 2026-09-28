"""OI-213 机制读数（preregister.md 读数 1，主证据）：研发资本化前后的年报 NOPAT、投入资本与 ROIC。

1. 具名公司 2017～最新财年逐年对照：研发、摊销、EBIT、NOPAT、IC、ROIC（调整前／后）；
2. ROIC 持续性：有研发公司 ROIC_t 与 ROIC_{t+2} 的逐年横截面秩相关（调整前／后），按摊销年限与研发强度（≥ 5% 营收）分组；
3. 非正 NOPAT 年份占比（调整前／后）。

    python3 mechanism.py      # → mechanism.json、mechanism.md
"""
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from scipy.stats import spearmanr

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import roic_inputs  # noqa: E402

NAMED = ('688235', '300661', '688777', '600570', '002594', '688018', '688041', '688012', '688111', '600276')
FIRST = 2017


def roic(years, period):
    y = years.get(period)
    prev = years.get(f'{int(period[:4]) - 1}-12-31')
    return roic_inputs.roic_of(y, prev) if y is not None else None


def main():
    with (EXP / 'a_share_csrc_industry.csv').open(encoding='utf-8', newline='') as f:
        industry = {r['security_code'].zfill(6): (r.get('security_name', ''), r.get('csrc_industry', '')) for r in csv.DictReader(f)}
    base = roic_inputs.load_statements(None, ic_floor=0.1, caliber='nonop', notice_cap=True, restricted_cash='notes_wc')
    rd = roic_inputs.load_rd_expense(set(base))
    adjusted, lives, intensity = {}, {}, {}
    for code, years in base.items():
        if not rd.get(code) or any(y.is_financial for y in years.values()):
            continue
        life = roic_inputs.rd_life(industry.get(code, ('', ''))[1])
        done = roic_inputs.capitalize_rd(years, rd[code], life)
        if done is None:
            continue
        adjusted[code], lives[code] = done[0], life
        rev = years.get(max(rd[code]))
        intensity[code] = rd[code][max(rd[code])] / rev.revenue if rev is not None and rev.revenue else None
    named = {}
    for code in NAMED:
        if code not in adjusted:
            named[code] = dict(name=industry.get(code, ('', ''))[0], status='无研发或无基年')
            continue
        rows = []
        for period in sorted(p for p in adjusted[code] if int(p[:4]) >= FIRST):
            b, a = base[code][period], adjusted[code][period]
            rows.append(dict(period=period[:4], rd=rd[code].get(period), amort=a.dep_amort - b.dep_amort, ebit=b.ebit, ebit_adj=a.ebit,
                             nopat=b.nopat, nopat_adj=a.nopat, ic=b.invested_capital, ic_adj=a.invested_capital,
                             roic=roic(base[code], period), roic_adj=roic(adjusted[code], period)))
        named[code] = dict(name=industry.get(code, ('', ''))[0], life=lives[code], rows=rows)
    # ROIC 持续性：ROIC_t 对 ROIC_{t+2} 的横截面秩相关
    groups = {'全部': set(adjusted), **{f'{n}年': {c for c, v in lives.items() if v == n} for n in (3, 5, 10)},
              '研发强度≥5%': {c for c, v in intensity.items() if v is not None and v >= 0.05},
              '研发强度<5%': {c for c, v in intensity.items() if v is not None and v < 0.05}}
    persistence = {}
    last = max(int(p[:4]) for ys in base.values() for p in ys)
    for g, codes in groups.items():
        by_year = {}
        for t in range(FIRST, last - 1):
            p0, p2 = f'{t}-12-31', f'{t + 2}-12-31'
            pairs_b = [(roic(base[c], p0), roic(base[c], p2)) for c in codes]
            pairs_a = [(roic(adjusted[c], p0), roic(adjusted[c], p2)) for c in codes]
            keep = [i for i, (x, y) in enumerate(pairs_b) if None not in (x, y) and None not in pairs_a[i]]
            if len(keep) < 10:
                continue
            rb = spearmanr([pairs_b[i][0] for i in keep], [pairs_b[i][1] for i in keep])[0]
            ra = spearmanr([pairs_a[i][0] for i in keep], [pairs_a[i][1] for i in keep])[0]
            by_year[t] = dict(n=len(keep), before=float(rb), after=float(ra))
        persistence[g] = dict(companies=len(codes), by_year=by_year,
                              mean_before=statistics.mean(v['before'] for v in by_year.values()) if by_year else None,
                              mean_after=statistics.mean(v['after'] for v in by_year.values()) if by_year else None,
                              after_higher_years=sum(v['after'] > v['before'] for v in by_year.values()))
    nonpos = defaultdict(lambda: [0, 0, 0])
    for code, years in adjusted.items():
        for period, a in years.items():
            b = base[code][period]
            if int(period[:4]) < FIRST or b.nopat is None:
                continue
            nonpos[lives[code]][0] += 1
            nonpos[lives[code]][1] += b.nopat <= 0
            nonpos[lives[code]][2] += a.nopat <= 0
    res = dict(companies=len(adjusted), lives={n: sum(v == n for v in lives.values()) for n in (3, 5, 10)},
               named=named, persistence=persistence,
               nonpositive_nopat={n: dict(years=v[0], before=v[1], after=v[2]) for n, v in sorted(nonpos.items())})
    (EXP / 'mechanism.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    fmt = lambda x, k=100: '—' if x is None else f'{x * k:.1f}'
    out = ['# OI-213 机制读数', '', f"有研发并资本化 {res['companies']} 家（摊销 3／5／10 年：{res['lives'][3]}／{res['lives'][5]}／{res['lives'][10]}）。", '',
           '## ROIC 持续性（ROIC_t 对 ROIC_{t+2} 横截面秩相关，逐年平均）', '', '| 组 | 公司 | 年数 | 调整前 | 调整后 | 调整后更高的年数 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for g, v in persistence.items():
        out.append(f"| {g} | {v['companies']} | {len(v['by_year'])} | {fmt(v['mean_before'], 1) if v['mean_before'] is not None else '—'} | "
                   f"{fmt(v['mean_after'], 1) if v['mean_after'] is not None else '—'} | {v['after_higher_years']} |")
    out += ['', '## 非正 NOPAT 年份（2017 年起）', '', '| 摊销年限 | 年份 | 调整前 | 调整后 |', '| ---: | ---: | ---: | ---: |']
    for n, v in res['nonpositive_nopat'].items():
        out.append(f"| {n} | {v['years']} | {v['before']} | {v['after']} |")
    out += ['', '## 具名公司（亿元；ROIC %）', '']
    for code, v in named.items():
        if 'rows' not in v:
            out.append(f"- {code} {v['name']}：{v['status']}")
            continue
        out += [f"### {code} {v['name']}（{v['life']} 年）", '', '| 年 | 研发 | 摊销 | NOPAT | NOPAT 调整后 | IC | IC 调整后 | ROIC | ROIC 调整后 |',
                '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        for r in v['rows']:
            e = lambda x: '—' if x is None else f'{x / 1e8:.1f}'
            out.append(f"| {r['period']} | {e(r['rd'])} | {e(r['amort'])} | {e(r['nopat'])} | {e(r['nopat_adj'])} | {e(r['ic'])} | {e(r['ic_adj'])} | "
                       f"{fmt(r['roic'])} | {fmt(r['roic_adj'])} |")
        out.append('')
    (EXP / 'mechanism.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out[:20]))


if __name__ == '__main__':
    main()

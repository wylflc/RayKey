"""OI-237 补充读数（preregister.md「补充」）：detail/ 的逐 (代码, 年) contrib →
逐年个股贡献差（整年在场的起点平均）与各年正负前三只。对 BASE 列 6 臂，另列 X3S15 对 S15、CCS15 对 S15。只描述，不进读数标记。

    python3 yearly.py     # → yearly.json、yearly.md
"""
import csv
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(EXP))
import sweep_backtest_configs as sw  # noqa: E402
from detail import DETAIL_ARMS  # noqa: E402

PAIRS = [(a, 'BASE') for a in DETAIL_ARMS if a != 'BASE'] + [('X3S15', 'S15'), ('CCS15', 'S15')]
NAMES = (ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv', ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv')
YEARS = range(2010, 2027)


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


def main():
    per = {}                                   # (臂, 起点) → {年: {代码: contrib}}
    for a in DETAIL_ARMS:
        for s in sw.DEFAULT_STARTS:
            d = json.loads((EXP / 'detail' / f"{sw.summary_tag(a + 'full', s, '')}.json").read_text())
            y = defaultdict(dict)
            for key, v in d['contrib_year'].items():
                code, yr = key.split('|')
                y[int(yr)][code] = v
            per[(a, s)] = y
    out = {}
    for a, r in PAIRS:
        rows = {}
        for y in YEARS:
            active = [s for s in sw.DEFAULT_STARTS if int(s[:4]) <= y - 1]      # 整年在场：起点早于该年 1 月 1 日
            if not active:
                continue
            diff = defaultdict(float)
            for s in active:
                ya, yr = per[(a, s)].get(y, {}), per[(r, s)].get(y, {})
                for code in set(ya) | set(yr):
                    diff[code] += (ya.get(code, 0.0) - yr.get(code, 0.0)) / len(active)
            ranked = sorted(diff.items(), key=lambda kv: kv[1])
            rows[y] = dict(n=len(active), total=sum(diff.values()), top=ranked[::-1][:3], bottom=ranked[:3])
        out[f'{a}|{r}'] = rows
    (EXP / 'yearly.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    nm = names()
    fmt = lambda xs: '、'.join(f"{nm.get(c, c)} {v * 100:+.1f}" for c, v in xs if abs(v) >= 0.005) or '—'
    md = ['# OI-237 补充：逐年个股贡献差（preregister.md「补充」）', '',
          '贡献 = 逐日「盈亏 ÷ 前一日净资产」按（代码, 年）累计，取整年在场起点的平均（pp）；2026 截至末次净值日。只描述，不进读数标记。', '']
    for key, rows in out.items():
        a, r = key.split('|')
        md += [f'## {a} 对 {r}', '', '| 年 | 起点数 | 合计 | 多赚前三 | 少赚前三 |', '| --- | ---: | ---: | --- | --- |']
        for y, v in rows.items():
            md.append(f"| {y} | {v['n']} | {v['total'] * 100:+.1f} | {fmt(v['top'])} | {fmt(v['bottom'])} |")
        md.append('')
    (EXP / 'yearly.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md[:40]))


if __name__ == '__main__':
    main()

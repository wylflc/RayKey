"""v4.224 落地读数的归因（参考）：CUR 与 K1 在 2009-11、2011-11 两个长跑起点上导出闭合周期（attrib_engine.py），按代码汇总 contrib（盈亏 ÷ 前一日净资产的累计贡献），
分银行与非银行报 K1 − CUR，并列出贡献差最大的代码与银行周期的建仓年份分布。只作解释，不改规则。

    python3 attrib.py      # → trades/、attribution.json、attribution.md
"""
import csv
import json
import os
import shlex
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from run import EXP, ROOT
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402
import bank_valuation  # noqa: E402

STARTS = ('2009-11-01', '2011-11-01')
# CUR 读 K7045（与安装前正式状态逐字节相同，安装 K1 后 data/processed 已不是旧口径）
STATES = {'CUR': EXP / 'states/K7045', 'K1': EXP / 'states/K1'}
NAMES = {r['security_code'].zfill(6): r.get('security_name', '') for r in csv.DictReader((ROOT / 'data/raw/a_share_securities.csv').open(encoding='utf-8-sig'))}
BANKS = bank_valuation.bank_codes(ROOT / 'data/raw/a_share_securities.csv')


def one(job):
    arm, start = job
    tag = sw.summary_tag(arm + 'tr', start)
    st = STATES[arm]
    out = EXP / 'trades' / f'{tag}_cycles.csv'
    cmd = [sys.executable, str(EXP / 'attrib_engine.py'), *shlex.split(sw.BASE), '--since', start,
           '--label-suffix', '_' + tag, '--out-dir', str(EXP / 'cache_tr'), '--equity-bond-log-dir', str(EXP / 'daily_tr'),
           '--daily-states', str(st / 'a_share_daily_states_adopted.csv'), '--hold-states', str(st / 'a_share_daily_states_hold.csv'),
           ]
    subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, check=True)
    return job, out


def load(path):
    by, bank_years = defaultdict(float), defaultdict(lambda: [0, 0.0])
    with path.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            c = float(r['contrib'] or 0.0)
            by[r['security_code']] += c
            if r['security_code'] in BANKS:
                y = bank_years[r['entry_date'][:4]]
                y[0] += 1; y[1] += c
    return by, bank_years


def main():
    for d in ('trades', 'cache_tr', 'daily_tr'):
        (EXP / d).mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = dict(pool.map(one, [(a, s) for a in STATES for s in STARTS]))
    res, md = {}, ['# v4.224 读数归因：K1 − CUR 的逐代码贡献差（contrib，pp，参考）', '']
    for s in STARTS:
        cur, cur_y = load(paths[('CUR', s)])
        k1, k1_y = load(paths[('K1', s)])
        codes = set(cur) | set(k1)
        delta = {c: k1.get(c, 0.0) - cur.get(c, 0.0) for c in codes}
        bank = sum(v for c, v in delta.items() if c in BANKS)
        other = sum(v for c, v in delta.items() if c not in BANKS)
        top = sorted(delta.items(), key=lambda kv: kv[1])
        years = sorted(set(cur_y) | set(k1_y))
        res[s] = dict(total=sum(delta.values()), bank=bank, nonbank=other,
                      bank_cur=sum(v for c, v in cur.items() if c in BANKS), bank_k1=sum(v for c, v in k1.items() if c in BANKS),
                      worst=[(c, v, cur.get(c, 0.0), k1.get(c, 0.0)) for c, v in top[:8]],
                      best=[(c, v, cur.get(c, 0.0), k1.get(c, 0.0)) for c, v in top[::-1][:8]],
                      bank_cycles_by_entry_year={y: dict(cur=cur_y.get(y, [0, 0.0]), k1=k1_y.get(y, [0, 0.0])) for y in years})
        pp = lambda v: f'{v * 100:+.1f}'
        r = res[s]
        md += [f'## 起点 {s}', '', f"合计 {pp(r['total'])}；银行 {pp(r['bank'])}（CUR {pp(r['bank_cur'])} → K1 {pp(r['bank_k1'])}）；非银行 {pp(r['nonbank'])}。", '',
               '| 代码 | 名称 | 银行 | CUR | K1 | K1 − CUR |', '| --- | --- | --- | ---: | ---: | ---: |']
        for c, v, a, b in r['worst'] + r['best']:
            md.append(f"| {c} | {NAMES.get(c, '')} | {'是' if c in BANKS else ''} | {pp(a)} | {pp(b)} | {pp(v)} |")
        md += ['', '银行周期按建仓年份（周期数／贡献 pp）：', '', '| 年份 | CUR | K1 |', '| --- | --- | --- |']
        for y, v in r['bank_cycles_by_entry_year'].items():
            md.append(f"| {y} | {v['cur'][0]}／{pp(v['cur'][1])} | {v['k1'][0]}／{pp(v['k1'][1])} |")
        md.append('')
    (EXP / 'attribution.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    (EXP / 'attribution.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md))


if __name__ == '__main__':
    main()

"""v4.225 落地核对（build.py 之后）：

1. NEW 对正式三侧：去掉保险行后逐字节相同（build.py 的逐行 zip 比对因 NEW 多出保险行而错位，改为分流核对）；
   保险行按（代码, 日期）计：改值、新增（原口径 V_D0 不可得而 V_DDM × Ḡ 可估）、消失。
2. 落地口径的月末 Ḡ 取自然月末，预登记检验（`../exp_oi232_20260930/`）取交易月末，二者在部分月份不同。
   用 NEW 状态的保险月末 V 按 OI-232 预登记读数 1～4 原式重算一遍（候选名 I1c_landed），与检验时的 I1c 并列。

    python3 verify_new.py    # → verify_new.json、verify_new.md
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
PROC = ROOT / 'data/processed'
OI232 = ROOT / 'data/experiments/exp_oi232_20260930'
sys.path.insert(0, str(OI232))
sys.path.insert(0, str(ROOT / 'scripts'))
import analyze as oi232  # noqa: E402
from divspread_names import INSURER_CODES  # noqa: E402

FILES = ('a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv')
PREFIXES = tuple(c + ',' for c in INSURER_CODES)


def split_digest(path: Path):
    """非保险行的 sha256 与保险行 {(代码, 日期): 行}。"""
    h, ins = hashlib.sha256(), {}
    with path.open('rb') as f:
        header = f.readline()
        h.update(header)
        for line in f:
            if line.startswith(tuple(p.encode() for p in PREFIXES)):
                parts = line.decode('utf-8').rstrip('\r\n').split(',')
                ins[(parts[0], parts[1])] = line
            else:
                h.update(line)
    return h.hexdigest(), ins


def compare(name):
    da, ia = split_digest(PROC / name)
    db, ib = split_digest(EXP / 'states/NEW' / name)
    common = ia.keys() & ib.keys()
    return dict(non_insurer_identical=da == db, insurer_rows_current=len(ia), insurer_rows_new=len(ib),
                insurer_changed=sum(ia[k] != ib[k] for k in common), insurer_added=len(ib.keys() - ia.keys()),
                insurer_removed=len(ia.keys() - ib.keys()),
                added_by_code={c: sum(1 for k in ib.keys() - ia.keys() if k[0] == c) for c in sorted(INSURER_CODES)}), ib


def landed_readings(ins_rows_new):
    v_new = {k: float(line.decode('utf-8').split(',')[7]) for k, line in ins_rows_new.items()}
    rows = oi232.load_ins()
    for r in rows:
        v = v_new.get((r['code'], r['date']))
        r['v_I1c_landed'] = v
        r['pv_I1c_landed'] = float(r['close']) / v if v else None
    diffs = [abs(r['v_I1c_landed'] / r['v_I1c'] - 1) for r in rows if r['v_I1c_landed'] and r['v_I1c']]
    ref = oi232.load_ref()
    rng = np.random.default_rng(oi232.SEED)
    out = dict(value_vs_tested=dict(months=len(diffs), median_rel_diff=float(np.median(diffs)), max_rel_diff=float(max(diffs)),
                                    over_1pct=sum(d > 0.01 for d in diffs)), same_ruler={})
    oi232.CANDS = ('I1c', 'I1c_landed')
    for label, panel_only, since, h in oi232.SAMPLES:
        out['same_ruler'][label] = {c: oi232.same_ruler(ref, rows, c, panel_only, since, h, rng) for c in ('I1c', 'I1c_landed')}
    out['dynamics'] = {c: oi232.dynamics(rows, c) for c in ('I1c', 'I1c_landed')}
    out['ranking'] = {c: oi232.ranking(rows, c) for c in ('I1c', 'I1c_landed')}
    return out


def main():
    res = dict(sides={})
    ins_new = None
    for name in FILES:
        res['sides'][name], ib = compare(name)
        if name == FILES[0]:
            ins_new = ib
        print(name, res['sides'][name], flush=True)
    res['landed'] = landed_readings(ins_new)
    (EXP / 'verify_new.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    pp = lambda v: f'{v * 100:+.2f}'
    ci = lambda v: f'[{v[0] * 100:+.2f}, {v[1] * 100:+.2f}]'
    lv = res['landed']
    md = ['# v4.225 落地核对', '', '| 侧 | 非保险行逐字节相同 | 保险行 现行→NEW | 改值 | 新增 | 消失 |', '| --- | --- | --- | ---: | ---: | ---: |']
    for name, s in res['sides'].items():
        md.append(f"| {name} | {'是' if s['non_insurer_identical'] else '否'} | {s['insurer_rows_current']}→{s['insurer_rows_new']} | "
                  f"{s['insurer_changed']} | {s['insurer_added']} | {s['insurer_removed']} |")
    v = lv['value_vs_tested']
    md += ['', f"落地口径（自然月末 Ḡ）对检验口径（交易月末 Ḡ）：{v['months']} 个保险月末，V 相对差中位 {v['median_rel_diff']:.4%}、最大 {v['max_rel_diff']:.2%}，"
               f"超过 1% 的 {v['over_1pct']} 个。", '', '| 样本 | I1c（检验）c_保险 | 区间 | I1c（落地）c_保险 | 区间 |', '| --- | ---: | --- | ---: | --- |']
    for label, e in lv['same_ruler'].items():
        a, b = e['I1c'], e['I1c_landed']
        md.append(f"| {label} | {pp(a['c_ins'])} | {ci(a['c_ins_ci'])} | {pp(b['c_ins'])} | {ci(b['c_ins_ci'])} |")
    md += ['', f"利率斜率（每 1pp）：检验 {lv['dynamics']['I1c']['rate_slope_per_pp']:+.3f}，落地 {lv['dynamics']['I1c_landed']['rate_slope_per_pp']:+.3f}；"
               f"保险内秩相关中位：检验 {lv['ranking']['I1c']['median']:+.2f}，落地 {lv['ranking']['I1c_landed']['median']:+.2f}。"]
    (EXP / 'verify_new.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md))


if __name__ == '__main__':
    main()

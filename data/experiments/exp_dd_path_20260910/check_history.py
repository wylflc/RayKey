"""v4.175 回撤通道的历史核对（§12.224）：把新判定套到仓库里全部 m2 扫描文件（同批自带 BASE 与剔除集 A 行）上，
列出哪些历史候选会经回撤通道进入「可采纳」，以及 m3 首批（§12.223）EBDS 臂的新判定。

m2 文件没有同窗序列，主读数改用旧主读数（滚 5 中位配对差 M）做 −1pp 下限核对；其余读数同现行规则。
用法：python3 data/experiments/exp_dd_path_20260910/check_history.py
"""
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402

M2_KEYS = (('主读数', '滚动5年年化中位'), ('复利读数', '年化'))
SKIP_U = re.compile(r'(^|_)(U\d*|strict_U|tiers_U)$')      # 固定剔除集 U 的单遍：第二表不是 A，不入核对


def m2_files():
    for f in sorted(ROOT.glob('data/experiments/**/sweep*.txt')):
        with f.open(encoding='utf-8', errors='replace') as fh:
            if not fh.readline().startswith('#METRIC|m2'):
                continue
        if SKIP_U.search(f.stem):
            continue
        yield f


def main():
    rows, counts = [], {'files': 0, 'arms': 0, 'old': {}, 'new': {}, 'entered_via_path': 0}
    for f in m2_files():
        groups, orders, failed, _note, version, _fields = sw.load_scan(f)
        full, ex = groups[''], groups[sw.EX5_PREFIX]
        if 'BASE' not in full or 'BASE' not in ex:
            continue
        counts['files'] += 1
        for label in orders['']:
            if label == 'BASE' or label not in ex:
                continue
            old, _r0, _v0 = sw.adoption_verdict(full, ex, label, verdict_keys=M2_KEYS, dd_path=False)
            new, reasons, vals = sw.adoption_verdict(full, ex, label, verdict_keys=M2_KEYS)
            counts['arms'] += 1
            counts['old'][old] = counts['old'].get(old, 0) + 1
            counts['new'][new] = counts['new'].get(new, 0) + 1
            deep = sum(1 for ep in vals['回撤段'] if ep['delta'] <= -sw.DD_PATH_MDD_GAIN)
            rec = {'file': str(f.relative_to(ROOT)), 'arm': label, 'old': old, 'new': new,
                   'M_full': vals['主读数'][0], 'M_A': vals['主读数'][1], 'C_full': vals['复利读数'][0], 'C_A': vals['复利读数'][1],
                   'MDD_full': vals['ΔMDD'][0], 'MDD_A': vals['ΔMDD'][1], 'worst_full': vals['Δ滚5最差'],
                   'episodes': f"{deep}/{len(vals['回撤段'])}", 'episode_text': sw._episode_text(vals['回撤段']), 'reasons': reasons}
            if new.startswith('可采纳·回撤通道'):
                counts['entered_via_path'] += 1
            # 回撤达标（两表 ≤ −5pp）但没走通道的臂也列出来，看是哪一条挡住
            mdd_ok = all(v == v for v in vals['ΔMDD']) and max(vals['ΔMDD']) <= -sw.DD_PATH_MDD_GAIN
            if new.startswith('可采纳·回撤通道') or (mdd_ok and old != '可采纳'):
                rows.append(rec)
    pct = lambda x: '—' if x != x else f'{x*100:+.2f}'
    lines = ['# v4.175 回撤通道历史核对（m2 扫描文件，主读数用旧 M 做下限）', '',
             f"文件 {counts['files']}，候选臂 {counts['arms']}；旧判定分布 {counts['old']}；新判定分布 {counts['new']}；经回撤通道进入可采纳 {counts['entered_via_path']} 臂",
             '', '## 经通道进入、或两表 ΔMDD ≤ −5pp 但未过通道的臂', '',
             '| 文件 | 臂 | 旧判定 | 新判定 | M 全/A | 复利 全/A | ΔMDD 全/A | Δ滚5最差 | 回撤段 | 段明细 |',
             '| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for r in rows:
        lines.append(f"| {r['file'].replace('data/experiments/', '')} | {r['arm']} | {r['old']} | {r['new']} | {pct(r['M_full'])}/{pct(r['M_A'])} | "
                     f"{pct(r['C_full'])}/{pct(r['C_A'])} | {pct(r['MDD_full'])}/{pct(r['MDD_A'])} | {pct(r['worst_full'])} | {r['episodes']} | {r['episode_text']} |")
    # m3 首批 EBDS 臂：现行规则（同窗主读数）下的新判定，直接取扫描器 --report 的【采纳判定】段
    buf = io.StringIO()
    with redirect_stdout(buf):
        sw.report(ROOT / 'data/experiments/exp_m3_rereg_20260910/sweep_full_A.txt', 'm3 首批 EBDS 臂在 v4.175 下的判定')
    block = buf.getvalue().split('【采纳判定】', 1)[1].split('\n\n', 1)[0]
    lines += ['', '## m3 首批（§12.223）EBDS 臂在 v4.175 下', '', '```', '【采纳判定】' + block.rstrip(), '```']
    (EXP / 'history_flips.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (EXP / 'summary.json').write_text(json.dumps({'counts': counts, 'rows': rows}, ensure_ascii=False, indent=1, default=str) + '\n', encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()

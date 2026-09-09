"""m3 首批同批重算（§12.223）：记账修复后的 BASE 在册重登 + EBDS02/EBDS03 全/A/U，判定翻转表与负现金核对。

用法：python3 data/experiments/exp_m3_rereg_20260910/run.py --workers 56   （SLURM 内）
      python3 data/experiments/exp_m3_rereg_20260910/run.py --report        （只重出表与翻转表）
"""
import argparse
import csv
import json
import os
import statistics as st
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw  # noqa: E402
import clean_derived_artifacts as archive  # noqa: E402
from dose_table import verdict  # noqa: E402

OLD = ROOT / 'data/experiments/exp_equity_bond_20260909/high_base'
AUDIT = ROOT / 'data/experiments/exp_rolling_metric_audit_20260909'
LEDGER_PREFIX = 'M3REG20260910_'
# v4.169 在册（§12.217 末段）：全样本 滚5中位/P25/最差、年化、最大回撤、块中位、逐年最差、换手、长跑 09/11；去赢家 滚5、年化、MDD、长跑
OLD_REGISTER = {'full': {'滚动5年年化中位': 52.00, '滚动5年年化P25': 40.99, '滚动5年年化最差': 10.84, '年化': 45.72,
                         '最大回撤': 66.9, '互不重叠5年块中位': 66.12, '逐年最差': -25.6, '年均换手': 6.63},
                'A': {'滚动5年年化中位': 52.66, '年化': 48.91, '最大回撤': 65.3}}
KEYS = (('主读数(同窗)', sw.WIN5_KEY), ('滚5中位差(m2主读数)', '滚动5年年化中位'), ('复利', '年化'),
        ('P25', '滚动5年年化P25'), ('滚5回撤', '滚动5年回撤中位'))


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


def sweep(config, out, workers, title, exclude=None, wrapper=False):
    cmd = [sys.executable, str(EXP / 'scan_ebds.py') if wrapper else str(ROOT / 'scripts/sweep_backtest_configs.py'),
           str(config), '--out', str(out), '--workers', str(workers), '--title', title]
    if wrapper:
        cmd += ['--cache-dir', str(EXP / 'summaries' / out.stem.replace('sweep_', ''))]   # summaries/full_A、summaries/U
    if exclude:
        cmd += ['--exclude-codes', ','.join(sorted(exclude))]
    with (EXP / f'report_{out.stem}.txt').open('w') as fh:
        subprocess.run(cmd, stdout=fh, cwd=ROOT, check=True)
    lines = [s for s in out.read_text().splitlines() if s and not s.startswith('#')]
    bad = [s for s in lines if s.endswith(('|ERR', '|EMPTY'))]
    assert not bad, bad
    return len(lines)


def rows_of(scan):
    groups, orders, failed, note, version, fields = sw.load_scan(scan)
    assert version == sw.METRIC_VERSION and not any(failed.values()), (scan, version, failed)
    return groups


def winners(summary_path):
    with summary_path.open(encoding='utf-8') as fh:
        row = [r for r in csv.DictReader(fh) if r['策略'].startswith('trend_')][-1]
    return {c for c in row['前五赢家'].split('/') if c}


def paired(groups, label, key, grp=''):
    arms = groups[grp]
    return sw._paired_median(arms, label, key)


def old_readings():
    """旧记账（m2）下 EBDS 的读数：现行 M／复利／P25／回撤取 §12.220 results.csv，同窗读数取 §12.222 family_check.txt。"""
    out = {}
    with (OLD / 'results.csv').open(encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r['arm'] in ('EBDS02', 'EBDS03'):
                out[r['arm']] = {'M_full': float(r['full_roll5_delta_pp']), 'M_A': float(r['A_roll5_delta_pp']),
                                 'C_full': float(r['full_cagr_delta_pp']), 'C_A': float(r['A_cagr_delta_pp']),
                                 'P25_full': float(r['full_p25_delta_pp']), 'DD_full': float(r['full_roll5dd_delta_pp']),
                                 'verdict': r['verdict']}
    for line in (AUDIT / 'family_check.txt').read_text(encoding='utf-8').splitlines():
        parts = line.split()
        if parts and parts[0] in out and len(parts) >= 8:
            out[parts[0]].update({'P_full': float(parts[3]), 'P_A': float(parts[5])})
    return out


def register(groups, prefix):
    files = []
    with tempfile.TemporaryDirectory(prefix='raykey_m3_') as temp:
        for grp, arms in groups.items():
            for label, starts in arms.items():
                if label == 'BASE' and grp == '':
                    continue                     # 全样本 BASE 已由正式扫描器落台账
                for start in starts:
                    src = EXP / 'summaries' / 'full_A' / f"summary_{sw.summary_tag(label, start, 'ex5' if grp else '')}.csv"
                    name = f'summary_{prefix}{src.name[len("summary_"):]}'
                    dst = Path(temp) / name
                    dst.write_bytes(src.read_bytes())
                    files.append(SimpleNamespace(path=dst, name=name))
        upd = archive.write_ledger(files)
    return {'registered_files': len(files), 'ledger_rows_added': upd.current_added}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=56)
    ap.add_argument('--report', action='store_true')
    args = ap.parse_args()
    manifest = {'started_beijing': now(), 'job_id': os.environ.get('SLURM_JOB_ID'), 'metric': sw.METRIC_VERSION,
                'base': sw.BASE, 'starts': sw.DEFAULT_STARTS, 'workers': args.workers}
    if not args.report:
        assert args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', args.workers))
        n_base = sweep(EXP / 'configs/base.txt', EXP / 'sweep_base.txt', args.workers, 'm3 首批：记账修复后 BASE 在册重登')
        assert n_base == 2 * len(sw.DEFAULT_STARTS), n_base
        n_ebds = sweep(EXP / 'configs/ebds.txt', EXP / 'sweep_full_A.txt', args.workers,
                       'm3 首批：EBDS02/EBDS03 对 BASE（记账修复后，全样本／剔除集 A）', wrapper=True)
        assert n_ebds == 3 * 2 * len(sw.DEFAULT_STARTS), n_ebds
        anchor = sw.EX5_ANCHOR_START
        a = winners(ROOT / 'data/backtest' / f"summary_{sw.summary_tag('BASE', anchor)}.csv")
        b = winners(EXP / 'summaries/full_A' / f"summary_{sw.summary_tag('EBDS03', anchor)}.csv")
        u = a | b
        manifest['winner_sets'] = {'A': sorted(a), 'B_EBDS03': sorted(b), 'U': sorted(u), 'U_equals_A': u == a}
        if u != a:
            n_u = sweep(EXP / 'configs/ebds.txt', EXP / 'sweep_U.txt', args.workers, 'm3 首批：剔除集 U 单遍', exclude=u, wrapper=True)
            assert n_u == 3 * len(sw.DEFAULT_STARTS), n_u
    base_groups = rows_of(EXP / 'sweep_base.txt')
    ebds_groups = rows_of(EXP / 'sweep_full_A.txt')
    u_groups = rows_of(EXP / 'sweep_U.txt') if (EXP / 'sweep_U.txt').exists() else None
    # ① 两次扫描的 BASE 行逐字段相同（正式扫描器 vs 候选包装）
    same = all(abs(base_groups[g]['BASE'][s][k] - ebds_groups[g]['BASE'][s][k]) < 1e-9
               for g in ('', 'EX5:') for s in sw.DEFAULT_STARTS for k in sw.FIELDS)
    same &= all(base_groups[g]['BASE'][s][sw.WIN5_KEY] == ebds_groups[g]['BASE'][s][sw.WIN5_KEY]
                for g in ('', 'EX5:') for s in sw.DEFAULT_STARTS)
    # ② 负现金核对
    neg = {f'{g or "full"}:{label}': sum(int(v['负现金日数']) for v in arms[label].values())
           for g, arms in base_groups.items() for label in arms}
    neg.update({f'ebds:{g or "full"}:{label}': sum(int(v['负现金日数']) for v in arms[label].values())
                for g, arms in ebds_groups.items() for label in arms})
    min_cash = min(v['最低现金'] for arms in base_groups.values() for label in arms for v in arms[label].values())
    # ③ 在册重登读数（水平中位）与对旧在册的差
    reg = {}
    for g, name in (('', 'full'), ('EX5:', 'A')):
        arm = base_groups[g]['BASE']
        level = lambda k: st.median(v[k] for v in arm.values())
        reg[name] = {k: level(k) * (100 if k not in ('年均换手',) else 1)
                     for k in ('滚动5年年化中位', '滚动5年年化P25', '滚动5年年化最差', '年化', '最大回撤',
                               '互不重叠5年块中位', '逐年最差', '年均换手', '滚动5年回撤中位')}
        reg[name]['长跑'] = {s: (arm[s]['年化'] * 100, arm[s]['最大回撤'] * 100) for s in sw.LONGRUN_STARTS if s in arm}
        reg[name]['负现金日数'] = sum(int(v['负现金日数']) for v in arm.values())
        reg[name]['最低现金'] = min(v['最低现金'] for v in arm.values())
    # 对旧记账 BASE（§12.220 summary_rows.csv，m2）的逐起点配对差：只描述记账修复的影响
    old_rows = {}
    with (OLD / 'summary_rows.csv').open(encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r['arm'] == 'BASE' and r['group'] in ('full', 'A'):
                old_rows[(r['group'], r['start'])] = r
    fix_effect = {}
    for g, name in (('', 'full'), ('EX5:', 'A')):
        arm = base_groups[g]['BASE']
        for k in ('年化', '滚动5年年化中位', '滚动5年年化P25', '最大回撤', '滚动5年回撤中位', '年均换手'):
            d = [(arm[s][k] - float(old_rows[(name, s)][k])) * 100 for s in sw.DEFAULT_STARTS if (name, s) in old_rows]
            fix_effect[f'{name}:{k}'] = {'median_pp': st.median(d), 'positive': sum(1 for v in d if v > 0), 'n': len(d)}
    # ④ 翻转表
    old = old_readings()
    flip = []
    for label in ('EBDS03', 'EBDS02'):
        new = {n: (paired(ebds_groups, label, k), paired(ebds_groups, label, k, 'EX5:')) for n, k in KEYS}
        new_u = {n: paired(u_groups, label, k, 'EX5:') if u_groups else float('nan') for n, k in KEYS}
        flip.append({'arm': label, 'old': old.get(label, {}),
                     'new': {n: {'full': a * 100, 'A': e * 100, 'U': new_u[n] * 100} for n, (a, e) in new.items()},
                     'new_verdict_m3': verdict(ebds_groups[''], ebds_groups['EX5:'], label)})
    lines = ['# EBDS 判定翻转表（旧记账 m2 → 记账修复 + m3）', '',
             '| 臂 | 记账 | 主读数 M 全/A | 同窗 P 全/A | 复利 全/A | P25 全 | 滚5回撤 全 | 判定 |', '| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for f in flip:
        o = f['old']
        if o:
            lines.append(f"| {f['arm']} | 旧记账（§12.220/§12.222） | {o['M_full']:+.2f}/{o['M_A']:+.2f} | {o.get('P_full', float('nan')):+.2f}/{o.get('P_A', float('nan')):+.2f} | "
                         f"{o['C_full']:+.2f}/{o['C_A']:+.2f} | {o['P25_full']:+.2f} | {o['DD_full']:+.2f} | m2 {o['verdict']}；m3 规则下按 P 为 {'通过' if min(o.get('P_full', -9), o.get('P_A', -9), o['C_full'], o['C_A']) >= -0.15 else '未通过'} |")
        n = f['new']
        lines.append(f"| {f['arm']} | 修复后（本批） | {n['滚5中位差(m2主读数)']['full']:+.2f}/{n['滚5中位差(m2主读数)']['A']:+.2f} | **{n['主读数(同窗)']['full']:+.2f}/{n['主读数(同窗)']['A']:+.2f}** | "
                     f"{n['复利']['full']:+.2f}/{n['复利']['A']:+.2f} | {n['P25']['full']:+.2f} | {n['滚5回撤']['full']:+.2f} | m3 {f['new_verdict_m3']} |")
    lines += ['', f"U 列（剔除集 U，仅描述）：" + '；'.join(f"{f['arm']} 主读数 {f['new']['主读数(同窗)']['U']:+.2f}、复利 {f['new']['复利']['U']:+.2f}" for f in flip)]
    (EXP / 'flip_table.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    # ⑤ 台账登记（候选与去赢家 BASE 行按前缀入账；全样本 BASE 已由正式扫描器落 data/backtest，同批归并）
    ledger = None
    if not args.report:
        base_files = [SimpleNamespace(path=p, name=p.name) for p in (ROOT / 'data/backtest').glob('summary_BASE*.csv')]
        upd = archive.write_ledger(base_files)
        ledger = {'base_rows_added': upd.current_added, **register(ebds_groups, LEDGER_PREFIX)}
    out = {'completed_beijing': now(), 'manifest': manifest, 'base_rows_identical_across_scans': same, 'old_register_v4169': OLD_REGISTER,
           'negative_cash_days': neg, 'min_cash_base': min_cash, 'in_register': reg, 'fix_effect_vs_old_base_pp': fix_effect,
           'flip': flip, 'ledger': ledger}
    (EXP / 'verification.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('base_rows_identical_across_scans', 'negative_cash_days', 'min_cash_base')}, ensure_ascii=False))
    print((EXP / 'flip_table.md').read_text(encoding='utf-8'))
    print('M3 REREG COMPLETE', flush=True)


if __name__ == '__main__':
    main()

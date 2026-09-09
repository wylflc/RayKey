"""v4.176 落地核对（§12.226）：新 BASE（引擎 --equity-bond-restore-above）正式扫描 28 路径，须与 §12.223 的 EBDS03 行逐值相同；
归并台账并重登在册读数。用法：python3 data/experiments/exp_ebds03_land_20260910/run.py --workers 56
"""
import argparse
import json
import statistics as st
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402
import clean_derived_artifacts as archive  # noqa: E402

REF = ROOT / 'data/experiments/exp_m3_rereg_20260910/sweep_full_A.txt'   # §12.223：EBDS03 走高基准包装引擎的 28 路径


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--workers', type=int, default=16); ap.add_argument('--report', action='store_true')
    args = ap.parse_args()
    out = EXP / 'sweep_base.txt'
    if not args.report:
        with (EXP / 'report_sweep_base.txt').open('w') as fh:
            subprocess.run([sys.executable, str(ROOT / 'scripts/sweep_backtest_configs.py'), str(EXP / 'configs/base.txt'), '--out', str(out),
                            '--workers', str(args.workers), '--title', 'v4.176 落地：股债总仓位上限并入 BASE 在册重登'], stdout=fh, cwd=ROOT, check=True)
    new, *_ = sw.load_scan(out)
    ref, *_ = sw.load_scan(REF)
    worst, n, bad = 0.0, 0, []
    for grp in ('', sw.EX5_PREFIX):
        a, b = new[grp]['BASE'], ref[grp]['EBDS03']
        assert set(a) == set(b) == set(sw.DEFAULT_STARTS), (grp, sorted(a), sorted(b))
        for s in sw.DEFAULT_STARTS:
            for k in sw.FIELDS:
                x, y = a[s][k], b[s][k]
                if x != x and y != y:
                    continue
                d = abs(x - y); n += 1; worst = max(worst, d)
                if d > 1e-9:
                    bad.append((grp or 'full', s, k, x, y))
            if a[s][sw.WIN5_KEY] != b[s][sw.WIN5_KEY]:
                bad.append((grp or 'full', s, 'WIN5', len(a[s][sw.WIN5_KEY]), len(b[s][sw.WIN5_KEY])))
    identical = not bad
    reg = {}
    for grp, name in (('', 'full'), (sw.EX5_PREFIX, 'A')):
        arm = new[grp]['BASE']
        level = lambda k: st.median(v[k] for v in arm.values()) * (100 if k != '年均换手' else 1)
        reg[name] = {k: level(k) for k in ('滚动5年年化中位', '滚动5年年化P25', '滚动5年年化最差', '年化', '最大回撤',
                                          '互不重叠5年块中位', '逐年最差', '年均换手', '滚动5年回撤中位')}
        reg[name]['长跑'] = {s: (arm[s]['年化'] * 100, arm[s]['最大回撤'] * 100) for s in sw.LONGRUN_STARTS if s in arm}
        reg[name]['负现金日数'] = sum(int(v['负现金日数']) for v in arm.values())
    ledger = None
    if not args.report:
        files = [SimpleNamespace(path=p, name=p.name) for p in (ROOT / 'data/backtest').glob('summary_BASE*.csv')]
        upd = archive.write_ledger(files)
        ledger = {'base_rows_added': upd.current_added, 'current_rows': len(upd.current)}
    result = {'completed_beijing': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'identical_to_ebds03': identical,
              'values_checked': n, 'max_abs_diff': worst, 'mismatches': bad[:20], 'in_register': reg, 'ledger': ledger}
    (EXP / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('identical_to_ebds03', 'values_checked', 'max_abs_diff', 'ledger')}, ensure_ascii=False))
    print('V4176 LAND COMPLETE' if identical else 'V4176 LAND MISMATCH')


if __name__ == '__main__':
    main()

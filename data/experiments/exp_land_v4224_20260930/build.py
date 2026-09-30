"""v4.224 落地（OI-244，用户 2026-09-30 裁定 B：取消银行同尺系数）第一段：由正式输入重建 §6.7 第 3 步。

两臂各建三侧（候选、B2、持仓）：
- K7045 = `h2:0.02:0.10:0.7045`，须逐字节复现现行正式逐日状态（证明重建链条与输入未漂移）；
- K1 = `h2:0.02:0.10:1`，即落地口径。
另核对 K1 相对正式状态只改银行（保险除外）行，且 V 恰为 ÷0.7045、`P/V` 恰为 ×0.7045。

    python3 build.py      # → states/<臂>/、build_check.json
"""
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
PROC = ROOT / 'data/processed'
MODES = {'K7045': 'h2:0.02:0.10:0.7045', 'K1': 'h2:0.02:0.10:1'}
SIDES = (('', 'a_share_daily_states_adopted.csv'), ('_b2', 'a_share_daily_states_b2.csv'))
FILES = ('a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv')
SCALE = 0.7045


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 24), b''):
            h.update(chunk)
    return h.hexdigest()


def build(arm: str) -> str:
    out = EXP / 'states' / arm
    out.mkdir(parents=True, exist_ok=True)
    for suffix, state in SIDES:
        with (out / f'rebuild{suffix or "_base"}.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT / 'scripts/rebuild_bank_bands.py'), MODES[arm], str(out / state),
                            str(PROC / f'roic_daily_raw{suffix}.csv'), str(PROC / f'roic_bands{suffix}.csv')],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, env=dict(os.environ, PYTHONUNBUFFERED='1'))
    subprocess.run([sys.executable, str(ROOT / 'scripts/build_hold_daily_states.py'), '--base', str(out / FILES[0]),
                    '--b2', str(out / FILES[1]), '--out', str(out / FILES[2])], cwd=ROOT, check=True)
    return arm


def compare_k1(name: str) -> dict:
    """K1 对正式：逐行比对，非银行行须完全相同，银行行 V ×(1/0.7045)、P/V ×0.7045（保险不变）。

    （2026-09-30 首跑把 P/V 的比例写反成 ÷0.7045，全部银行行误报不符；更正后以 recheck.py 重跑本项。）"""
    from divspread_names import INSURER_CODES
    import bank_valuation
    banks = bank_valuation.bank_codes(ROOT / 'data/raw/a_share_securities.csv')
    stats = dict(rows=0, same=0, bank_changed=0, bank_ratio_bad=0, other_changed=0, insurer_changed=0)
    with (PROC / name).open(newline='', encoding='utf-8') as fa, (EXP / 'states/K1' / name).open(newline='', encoding='utf-8') as fb:
        ra, rb = csv.reader(fa), csv.reader(fb)
        ha, hb = next(ra), next(rb)
        assert ha == hb, name
        ic, iv, ip = ha.index('security_code'), ha.index('intrinsic_value'), ha.index('valuation_ratio')
        for a, b in zip(ra, rb):
            stats['rows'] += 1
            if a == b:
                stats['same'] += 1
                continue
            code = a[ic]
            if code in INSURER_CODES:
                stats['insurer_changed'] += 1
            elif code in banks:
                stats['bank_changed'] += 1
                try:
                    va, vb, pa, pb = float(a[iv]), float(b[iv]), float(a[ip]), float(b[ip])
                    ok = math.isclose(vb * SCALE, va, rel_tol=2e-4, abs_tol=2e-4) and math.isclose(pb, pa * SCALE, rel_tol=5e-4, abs_tol=2e-4)
                except ValueError:
                    ok = False
                stats['bank_ratio_bad'] += not ok
            else:
                stats['other_changed'] += 1
    return stats


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(build, MODES))
    check = dict(modes=MODES, reproduction={}, k1_vs_current={})
    for name in FILES:
        cur, rep = digest(PROC / name), digest(EXP / 'states/K7045' / name)
        check['reproduction'][name] = dict(current=cur, k7045=rep, identical=cur == rep)
        check['k1_vs_current'][name] = compare_k1(name)
        print(name, check['reproduction'][name]['identical'], check['k1_vs_current'][name], flush=True)
    for name in FILES:
        check['k1_vs_current'][name]['sha256'] = digest(EXP / 'states/K1' / name)
    (EXP / 'build_check.json').write_text(json.dumps(check, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()

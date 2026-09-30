"""v4.225 落地（OI-232，用户 2026-09-30 裁定按推荐 I1c：保险 V = V_DDM × 前 36 个自然月末银行 G 的中位）第一段：由正式输入重建 §6.7 第 3 步。

两臂各建三侧（候选、B2、持仓）：
- OLD = `h2:0.02:0.10:1:insd0`（保险 V_D0），须逐字节复现现行正式逐日状态（v4.224 安装的 K1）；
- NEW = `h2:0.02:0.10`（生产缺省，保险 V_DDM × Ḡ）。
另核对 NEW 相对正式状态只改保险行，且候选侧保险月末 V 与 OI-232 预登记检验的 I1c 值（`../exp_oi232_20260930/candidates.csv`）一致。

（本脚本的逐行 zip 比对假定行数相同；NEW 多出 220 个保险行（原口径 V_D0 不可得的日子）后错位，改以 `verify_new.py` 按保险行分流核对；
I1c 对照的相对差来自月末取法：落地取自然月末，检验取交易月末，见 `verify_new.md`。）

    python3 build.py      # → states/<臂>/、build_check.json
"""
import csv
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
PROC = ROOT / 'data/processed'
MODES = {'OLD': 'h2:0.02:0.10:1:insd0', 'NEW': 'h2:0.02:0.10'}
SIDES = (('', 'a_share_daily_states_adopted.csv'), ('_b2', 'a_share_daily_states_b2.csv'))
FILES = ('a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv')
CANDIDATES = ROOT / 'data/experiments/exp_oi232_20260930/candidates.csv'


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


def compare_new(name: str) -> dict:
    """NEW 对正式：逐行比对，只有保险行可以不同。"""
    from divspread_names import INSURER_CODES
    import bank_valuation
    banks = bank_valuation.bank_codes(ROOT / 'data/raw/a_share_securities.csv')
    stats = dict(rows=0, same=0, insurer_changed=0, bank_changed=0, other_changed=0)
    with (PROC / name).open(newline='', encoding='utf-8') as fa, (EXP / 'states/NEW' / name).open(newline='', encoding='utf-8') as fb:
        ra, rb = csv.reader(fa), csv.reader(fb)
        ha, hb = next(ra), next(rb)
        assert ha == hb, name
        ic = ha.index('security_code')
        for a, b in zip(ra, rb):
            stats['rows'] += 1
            if a == b:
                stats['same'] += 1
            elif a[ic] in INSURER_CODES:
                stats['insurer_changed'] += 1
            elif a[ic] in banks:
                stats['bank_changed'] += 1
            else:
                stats['other_changed'] += 1
    return stats


def check_candidates() -> dict:
    """NEW 候选侧保险 V 对预登记检验 I1c 的月末值（相对差）。"""
    want = {}
    with CANDIDATES.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['v_I1c']:
                want[(r['code'], r['date'])] = float(r['v_I1c'])
    got = {}
    prefixes = tuple(c + ',' for c in {c for c, _ in want})
    with (EXP / 'states/NEW' / FILES[0]).open(newline='', encoding='utf-8') as f:
        header = next(csv.reader([f.readline()]))
        ic, idt, iv = (header.index(k) for k in ('security_code', 'date', 'intrinsic_value'))
        for line in f:
            if line.startswith(prefixes):
                row = next(csv.reader([line]))
                if (row[ic], row[idt]) in want:
                    got[(row[ic], row[idt])] = float(row[iv])
    diffs = sorted(abs(got[k] / v - 1) for k, v in want.items() if k in got)
    return dict(candidate_months=len(want), matched=len(diffs), missing=len(want) - len(diffs),
                max_rel_diff=diffs[-1] if diffs else None, over_1e3=sum(d > 1e-3 for d in diffs))


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(build, MODES))
    check = dict(modes=MODES, reproduction={}, new_vs_current={})
    for name in FILES:
        cur, rep = digest(PROC / name), digest(EXP / 'states/OLD' / name)
        check['reproduction'][name] = dict(current=cur, old=rep, identical=cur == rep)
        check['new_vs_current'][name] = dict(compare_new(name), sha256=digest(EXP / 'states/NEW' / name))
        print(name, check['reproduction'][name]['identical'], check['new_vs_current'][name], flush=True)
    check['i1c_candidates'] = check_candidates()
    print('I1c', check['i1c_candidates'], flush=True)
    (EXP / 'build_check.json').write_text(json.dumps(check, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()

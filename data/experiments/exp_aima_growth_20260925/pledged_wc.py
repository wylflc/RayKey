"""OI-220 量级：质押开票存单计入营运资金（`--restricted-cash notes_wc`）对池内 79 只有质押存单公司最新带的影响。

两臂同为 v4.206 生产命令，只换 `--restricted-cash notes` / `notes_wc`，`--codes` 子集重建，比最新一条带（研究数叠加前的机械值）。
    python3 pledged_wc.py            # 两臂并行建带后汇总
"""
import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'data/experiments/exp_oi217_20260925'))
from common import PRODUCTION  # noqa: E402  v4.206 生产命令（含 --restricted-cash notes）

CODES = (EXP / 'pledged_codes.txt').read_text().strip()
BASE = [a for a in PRODUCTION if a != '--all']
i = BASE.index('--restricted-cash')


def build(mode: str) -> Path:
    out = EXP / 'pledged_wc' / mode
    out.mkdir(parents=True, exist_ok=True)
    args = BASE[:i + 1] + [mode] + BASE[i + 2:]
    with (out / 'build.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_historical_valuation_bands.py'), '--codes', CODES, *args,
                        '--out-bands', str(out / 'bands.csv'), '--out-daily', str(out / 'daily.csv')],
                       cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
    return out / 'bands.csv'


def latest(path: Path) -> dict:
    rows = {}
    for r in csv.DictReader(path.open()):
        if r['security_code'] not in rows or r['report_date'] >= rows[r['security_code']]['report_date']:
            rows[r['security_code']] = r
    return rows


def main():
    with ThreadPoolExecutor(2) as pool:
        base, wc = pool.map(build, ('notes', 'notes_wc'))
    a, b = latest(base), latest(wc)
    num = lambda r, k: float(r[k]) if r.get(k) not in (None, '') else None  # noqa: E731
    out = []
    for code in sorted(a):
        va, vb = num(a[code], 'intrinsic_value'), num(b[code], 'intrinsic_value')
        out.append(dict(code=code, name=a[code]['security_name'], path=a[code]['roic_path'], g_source=a[code].get('roic_g_source'),
                        rr=[num(a[code], 'reinvestment_rate'), num(b[code], 'reinvestment_rate')], g0=[num(a[code], 'g0'), num(b[code], 'g0')],
                        V=[va, vb], dV=(vb / va - 1) if va and vb else None))
    changed = [r for r in out if r['dV'] not in (None, 0.0)]
    changed.sort(key=lambda r: -abs(r['dV']))
    dvs = sorted(r['dV'] for r in changed)
    summary = dict(codes=len(out), changed=len(changed), up=sum(d > 0 for d in dvs), down=sum(d < 0 for d in dvs),
                   median=dvs[len(dvs) // 2] if dvs else None, rows=changed)
    (EXP / 'pledged_wc.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n')
    for r in changed[:25]:
        print(r['code'], r['name'], r['g_source'], 'RR', r['rr'], 'g0', r['g0'], f"V {r['V'][0]:.2f}->{r['V'][1]:.2f} ({r['dV']:+.1%})")
    print({k: v for k, v in summary.items() if k != 'rows'})


if __name__ == '__main__':
    main()

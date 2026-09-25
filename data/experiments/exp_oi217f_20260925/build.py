"""OI-217 公允性检验：`W`（净负债加权）在 v4.208 生产命令与 exp_oi217u 冻结输入上另建候选侧（base + 银行覆盖），
并与 exp_oi217u 的 `C`／`U` 带逐行核对（preregister.md「数据」）。

    python3 build.py              # 核对冻结输入 → 建带 → 银行覆盖 → 核对
    python3 build.py bands|bank   # 单步（子进程）
"""
import csv
import hashlib
import importlib.util
import itertools
import json
import os
import runpy
import subprocess
import sys
import types
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
SRC = ROOT / 'data/experiments/exp_oi217u_20260925'
spec = importlib.util.spec_from_file_location('oi217u_common', SRC / 'common.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
sys.path.insert(0, str(ROOT / 'scripts'))

OUT = EXP / 'states/W_build'
FLAGS = ['--wacc-weights', 'net']
R = 0.10


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return h.hexdigest()


def check_inputs() -> dict:
    manifest = json.loads((SRC / 'before_manifest.json').read_text())
    changed = [rel for rel, d in manifest['inputs'].items() if rel != 'frozen_actions'
               and (not (ROOT / rel).exists() or (ROOT / rel).stat().st_size != d['bytes'] or sha(ROOT / rel) != d['sha256'])]
    assert sha(u.FROZEN_ACTIONS) == manifest['inputs']['frozen_actions']['sha256'], 'frozen actions changed'
    assert not changed, f'inputs changed since the exp_oi217u freeze: {changed[:10]}'
    return dict(files=len(manifest['inputs']), revision=manifest['revision'])


def child(task: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw, bands = OUT / 'roic_daily_raw.csv', OUT / 'roic_bands.csv'
    if task == 'bands':
        path = ROOT / 'scripts/build_historical_valuation_bands.py'
        module = types.ModuleType('exp_build'); module.__file__ = str(path)
        sys.modules[module.__name__] = module
        exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
        module.ACTIONS = u.FROZEN_ACTIONS
        module.STMT_GAP_LOG = OUT / 'gaps.csv'
        sys.argv = ['build', *u.PRODUCTION, *FLAGS, '--out-bands', str(bands), '--out-daily', str(raw)]
        raise SystemExit(module.main())
    if task == 'bank':
        import build_historical_valuation_bands as valuation
        valuation.ACTIONS = u.FROZEN_ACTIONS
        import divspread_dividend as div
        original = div.load_distributions
        div.load_distributions = lambda *a, **k: original(u.FROZEN_ACTIONS)
        sys.argv = ['bank', 'divspread:0.02', str(OUT / 'a_share_daily_states_adopted.csv'), str(raw), str(bands)]
        runpy.run_path(str(ROOT / 'scripts/rebuild_bank_bands.py'), run_name='__main__')


def run(task: str) -> None:
    with (EXP / f'build_W_{task}.log').open('w') as f:
        subprocess.run([sys.executable, __file__, task], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True,
                       env=dict(os.environ, PYTHONUNBUFFERED='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1'))
    print('DONE', task, flush=True)


def validate() -> dict:
    """同一行键下逐行核对 W 带：不用 WACC 的路径与 C、U 逐位相同；C 与 U 逐位相同（无有息负债）时 W 也相同；
    其余 V 须介于 U 与 C 之间（U 拒绝时不高于 C）；印出的 wacc_W 等于 r 或 wacc_C 时，V 与对应臂相对差 < 0.3%（wacc 只印 4 位小数）。"""
    files = [OUT / 'roic_bands.csv', SRC / 'states/CONTROL_build/roic_bands.csv', SRC / 'states/WU_build/roic_bands.csv']
    handles = [p.open(newline='', encoding='utf-8') for p in files]
    counts = dict(rows=0, no_wacc=0, no_debt=0, near_U=0, near_C=0, between=0, rejected_W=0, rejected_W_ok_C=0)
    bad = []
    key = ('security_code', 'report_date', 'available_at')

    def flag(w, c, v, why):
        bad.append([w[k] for k in key] + [why, w['intrinsic_value'], c['intrinsic_value'], v['intrinsic_value']])

    try:
        for w, c, v in itertools.zip_longest(*(csv.DictReader(h) for h in handles)):
            assert w is not None and c is not None and v is not None, 'row counts differ'
            counts['rows'] += 1
            assert all(w[k] == c[k] == v[k] for k in key), [w[k] for k in key]
            if w['status'] != 'ok':
                counts['rejected_W'] += 1
                counts['rejected_W_ok_C'] += c['status'] == 'ok'
                if v['status'] == 'ok':
                    flag(w, c, v, 'W 拒绝而 U 可估')
                continue
            if c['status'] != 'ok':
                flag(w, c, v, 'W 可估而 C 拒绝')
                continue
            if not w['wacc']:   # equity_fallback 等不用 WACC 的路径
                counts['no_wacc'] += 1
                if not w['intrinsic_value'] == c['intrinsic_value'] == v['intrinsic_value']:
                    flag(w, c, v, '不用 WACC 的路径不一致')
                continue
            vw, vc = float(w['intrinsic_value']), float(c['intrinsic_value'])
            vu = float(v['intrinsic_value']) if v['status'] == 'ok' else None
            if c['intrinsic_value'] == v['intrinsic_value']:
                counts['no_debt'] += 1
                if w['intrinsic_value'] != c['intrinsic_value']:
                    flag(w, c, v, '无负债行不一致')
                continue
            lo, hi = (vc, vc) if vu is None else (min(vu, vc), max(vu, vc))   # 终值为负等少数行 V 随 WACC 上升
            if not (vu is None and vw <= vc + 1e-4 or lo - 1e-4 <= vw <= hi + 1e-4):
                flag(w, c, v, 'V 不在 U 与 C 之间')
            elif abs(float(w['wacc']) - R) < 1e-12 and vu is not None and abs(vw / vu - 1) >= 0.003:
                flag(w, c, v, 'wacc_W 印为 r 而 V 偏离 U')
            elif w['wacc'] == c['wacc'] and abs(vw / vc - 1) >= 0.003:
                flag(w, c, v, 'wacc_W 印同 C 而 V 偏离 C')
            elif abs(float(w['wacc']) - R) < 1e-12:
                counts['near_U'] += 1
            elif w['wacc'] == c['wacc']:
                counts['near_C'] += 1
            else:
                counts['between'] += 1
    finally:
        for h in handles:
            h.close()
    return dict(counts=counts, mismatches=len(bad), sample=bad[:20])


def main() -> None:
    report = dict(inputs=check_inputs(), job_id=os.getenv('SLURM_JOB_ID'), flags=[*u.PRODUCTION, *FLAGS])
    print('INPUTS', report['inputs'], flush=True)
    run('bands')
    run('bank')
    report['validation'] = validate()
    (EXP / 'build_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('VALIDATION', report['validation']['counts'], 'mismatches', report['validation']['mismatches'], flush=True)
    # 不在此断言：先读 build_validation.json 再决定是否进入分析


if __name__ == '__main__':
    if len(sys.argv) > 1:
        child(sys.argv[1])
    else:
        main()

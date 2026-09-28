"""影子组合代码迁移核验（2026-09-28 晚）：冻结文件 screen_daily_volume_price_signals.py 在 v4.219（OI-227）增银行同尺系数
（`bank_live_value` 退回股利利差时同样乘 `bank_valuation.BANK_SCALE`，买入线常数按对齐结果）后，按先例证明旧码复现存档状态、新旧回放逐项相等，再登记显式迁移。

    python3 validate.py            # 只核验，写 validation.json
    python3 validate.py --install  # 核验通过后写 migrations/oi227_scan_20260928.json 并更新 manifest 代码指纹
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
BOOK = ROOT / 'data/processed/shadow_portfolio/since_20260828'
OLD = {'screen_daily_volume_price_signals.py': '3483db8b^'}
MIGRATION = 'migrations/oi227_scan_20260928.json'
sha = lambda b: hashlib.sha256(b).hexdigest()

ARM = r'''
import hashlib, json, sys, types
from pathlib import Path
sys.path.insert(0, sys.argv[2])
if sys.argv[1] != sys.argv[2]:   # 旧码臂：旧源码按原路径执行并预先登记，任何 import 都拿到旧模块
    for f in [f for f in ('corporate_actions.py', 'screen_daily_volume_price_signals.py') if (Path(sys.argv[1]) / f).exists()]:
        mod = types.ModuleType(f[:-3]); mod.__file__ = str(Path(sys.argv[2]) / f); sys.modules[mod.__name__] = mod
        exec(compile((Path(sys.argv[1]) / f).read_bytes(), mod.__file__, 'exec'), mod.__dict__)
        mod.__source_sha256__ = hashlib.sha256((Path(sys.argv[1]) / f).read_bytes()).hexdigest()
import shadow_from_origin as so, shadow_portfolio as sh
book = so.BOOK
manifest = json.loads((book/'manifest.json').read_text())
snapshots = [json.loads((book/'snapshots'/f'{d}.json').read_text()) for d in sorted(manifest['snapshots'])]
supplement = {c: json.loads((book/'supplement'/f'{c}.json').read_text())['rows'] for c in manifest['supplemental_prices']}
for name in sorted(manifest.get('price_updates', {})):
    u = json.loads((book/name).read_text()); supplement[u['code']] = so.merge_prices(supplement.get(u['code'], []), u['rows'])
for name in manifest.get('action_corrections', {}):
    snapshots = so.corrected_actions(snapshots, json.loads((book/name).read_text()))
out = {}
for name, shares in manifest['scenarios'].items():
    out[name] = so.replay(snapshots, supplement, manifest, shares)
src = {m: getattr(sys.modules[m], '__source_sha256__', hashlib.sha256(Path(sys.modules[m].__file__).read_bytes()).hexdigest())
       for m in ('screen_daily_volume_price_signals', 'corporate_actions')}
print(json.dumps({'modules': src, 'result': out}, default=str))
'''


def run_arm(first: str) -> dict:
    proc = subprocess.run([sys.executable, '-c', ARM, first, str(ROOT / 'scripts')], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode:
        raise SystemExit(proc.stderr[-3000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main(install: bool) -> None:
    manifest = json.loads((BOOK / 'manifest.json').read_text())
    for day, h in manifest['snapshots'].items():
        assert sha((BOOK / 'snapshots' / f'{day}.json').read_bytes()) == h, day
    for name, h in {**manifest.get('action_corrections', {}), **manifest.get('code_migrations', {}), **manifest.get('price_updates', {})}.items():
        assert sha((BOOK / name).read_bytes()) == h, name
    with tempfile.TemporaryDirectory() as tmp:
        for f, commit in OLD.items():
            blob = subprocess.run(['git', 'show', f'{commit}:scripts/{f}'], capture_output=True, check=True, cwd=ROOT).stdout
            assert sha(blob) == manifest['code_sha256'][f], f
            (Path(tmp) / f).write_bytes(blob)
        old = run_arm(tmp)
    new = run_arm(str(ROOT / 'scripts'))
    for f in OLD:
        assert old['modules'][f[:-3]] == manifest['code_sha256'][f], ('OLD arm', f)
        assert new['modules'][f[:-3]] != manifest['code_sha256'][f], ('NEW arm', f)
    outcomes = {}
    for name in manifest['scenarios']:
        o, n = old['result'][name], new['result'][name]
        stored = json.loads((BOOK / name / 'states.json').read_text())
        same_states = json.loads(json.dumps(o[2], default=str)) == stored
        equal = [a == b for a, b in zip(o, n)]
        assert same_states, 'frozen OLD failed to reproduce stored shadow states'
        assert all(equal), equal
        outcomes[name] = dict(old_reproduces_stored_states=same_states, old_new_equal=equal, days=len(n[0]), fills=len(n[1]), last_equity=n[0][-1])
    current = {f: sha((ROOT / 'scripts' / f).read_bytes()) for f in manifest['code_sha256']}
    record = dict(outcomes=outcomes, original_snapshots=len(manifest['snapshots']),
                  changed_files={f: dict(before=manifest['code_sha256'][f], after=current[f], old_source=f'git {c}:scripts/{f}') for f, c in OLD.items()},
                  changed_names={'screen_daily_volume_price_signals.py': ['bank_live_value', 'SEC93_BUY_LINE 注释（值不变）']},
                  replay_references='shadow_from_origin／shadow_portfolio／backtest_valuation_strategy 均不引用 SEC93_BUY_LINE；买入线由每日快照 base 的 --width 冻结',
                  code_before=manifest['code_sha256'], code_after=current)
    (EXP / 'validation.json').write_text(json.dumps(record, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(outcomes, ensure_ascii=False, indent=1))
    if install:
        before = sha((BOOK / 'manifest.json').read_bytes())
        (EXP / 'shadow_manifest_before.json').write_bytes((BOOK / 'manifest.json').read_bytes())
        target = BOOK / MIGRATION
        assert not target.exists()
        migration = dict(issue='OI-227 银行同尺系数与买入线常数（v4.219）', created_at_beijing=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                         before_code_sha256=manifest['code_sha256'], after_code_sha256=current, before_manifest_sha256=before,
                         validation='data/experiments/shadow_migration_oi227_scan_20260928/validation.json',
                         validation_sha256=sha((EXP / 'validation.json').read_bytes()),
                         original_snapshots_unchanged=True, replay_economics_unchanged=True)
        target.write_text(json.dumps(migration, ensure_ascii=False, indent=2) + '\n')
        manifest['code_sha256'] = current
        manifest.setdefault('code_migrations', {})[MIGRATION] = sha(target.read_bytes())
        (BOOK / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        print('installed', MIGRATION)


if __name__ == '__main__':
    main('--install' in sys.argv)

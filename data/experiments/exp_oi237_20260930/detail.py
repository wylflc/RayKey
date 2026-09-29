"""OI-237 补充读数（preregister.md「补充」）：在 OI-236 补丁之上再加一处只记账的内存补丁——逐 (代码, 年) 累计 contrib，
不进任何交易判据。BASE／BTNS／BS15／S15／X3S15／CCS15／X3CCS15 × 14 起点全样本；每条路径的期末资产须与本批
summary_rows.csv 逐位相同。

    python3 detail.py          # 驱动：并行跑 98 条路径 → detail/<标签>.json，核对期末资产
"""
import csv
import json
import os
import shlex
import subprocess
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(EXP))
DETAIL_ARMS = ('BASE', 'BTNS', 'BS15', 'S15', 'X3S15', 'CCS15', 'X3CCS15')

EXTRA = [
    ('''    contrib: dict[str, float] = collections.defaultdict(float)
''',
     '''    contrib: dict[str, float] = collections.defaultdict(float)
    contrib_year: dict = collections.defaultdict(float)   # OI-237 补充：逐 (代码, 年) 累计
'''),
    ('''                contrib[code] += share
''',
     '''                contrib[code] += share
                contrib_year[(code, day[:4])] += share
'''),
    ('''"contrib": dict(contrib), "bb_log": bb_log,''',
     '''"contrib": dict(contrib), "contrib_year": {f"{c}|{y}": v for (c, y), v in contrib_year.items()}, "bb_log": bb_log,'''),
]


def engine():
    sys.path.insert(0, str(ROOT / 'data/experiments/exp_oi236_20260929'))
    from patch import SRC, patched_source
    text = patched_source()
    for old, new in EXTRA:
        assert text.count(old) == 1, ('anchor not unique', old[:60])
        text = text.replace(old, new)
    mod = types.ModuleType('backtest_valuation_strategy')
    mod.__file__ = str(SRC)
    sys.modules['backtest_valuation_strategy'] = mod
    exec(compile(text, str(SRC), 'exec'), mod.__dict__)
    mod.ACTIONS = Path(os.environ['EXP_ACTIONS_FILE'])
    out = Path(os.environ['DETAIL_OUT'])
    original = mod.summarize

    def capture(name, result, capital, benchmark, risk_free):
        if name.startswith('trend_'):
            out.write_text(json.dumps(dict(final_equity=result['equity'][-1][1], contrib_year=result['contrib_year']), ensure_ascii=False) + '\n')
        return original(name, result, capital, benchmark, risk_free)
    mod.summarize = capture
    raise SystemExit(mod.main())


def one(job):
    import sweep_backtest_configs as sw
    from run import ACTIONS, ARMS, STATES
    arm, start = job
    tag = sw.summary_tag(arm + 'full', start, '')
    out = EXP / 'detail' / f'{tag}.json'
    cmd = [sys.executable, str(Path(__file__)), '--engine', *shlex.split(sw.BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'detail_cache'), '--equity-bond-log-dir', str(EXP / 'detail_daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    with (EXP / 'detail_errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f,
                           env=dict(os.environ, EXP_ACTIONS_FILE=str(ACTIONS), DETAIL_OUT=str(out)))
    assert p.returncode == 0, (tag, p.returncode)
    return arm, start, json.loads(out.read_text())['final_equity']


def main():
    import sweep_backtest_configs as sw
    for name in ('detail', 'detail_cache', 'detail_daily', 'detail_errors'):
        (EXP / name).mkdir(exist_ok=True)
    registered = {(r['arm'], r['start']): float(r['期末资产']) for r in csv.DictReader((EXP / 'summary_rows.csv').open(encoding='utf-8'))
                  if r['group'] == 'full'}
    jobs = [(a, s) for a in DETAIL_ARMS for s in sw.DEFAULT_STARTS]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('WORKERS', 14))) as pool:
        got = list(pool.map(one, jobs))
    bad = [(a, s, e, registered[(a, s)]) for a, s, e in got if abs(e - registered[(a, s)]) > 1e-6 * max(1.0, abs(registered[(a, s)]))]
    (EXP / 'detail' / 'check.json').write_text(json.dumps(dict(paths=len(got), mismatches=bad), ensure_ascii=False) + '\n')
    assert not bad, bad
    print(f'{len(got)} paths, final equity reproduced')


if __name__ == '__main__':
    if '--engine' in sys.argv:
        sys.argv.remove('--engine')
        engine()
    else:
        main()

"""OI-167 landing.

Guardrail run: the fixed engine on the in-register inputs (old state subset + reference tables restored from git at the
registered hashes) paired against the registered BASE (exp_c030r35_land_20260910) — isolates the engine change (track A).
Registration run: the fixed engine on a fresh, digest-verified subset of current production states with frozen copies of
the current reference tables — becomes the new registered BASE and the common input set for exp_oi174_requal_20260913."""
import argparse
import contextlib
import csv
import hashlib
import json
import math
import os
import shlex
import shutil
import statistics as st
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
REF = EXP.parent / 'exp_c030r35_land_20260910'
WC = EXP.parent / 'exp_oi168_wc_20260909'
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw

GUARD_STAT = '单股上限·余量不足一手·跳过'
REFERENCE_INPUTS = ('data/raw/corporate_actions/a_share_corporate_actions.csv', 'data/reference/cost_of_equity_inputs.csv',
                    'data/reference/equity_bond_csi300.csv')


def read(path):
    with Path(path).open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def save(name, obj):
    (EXP / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def write(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(paths):
    return {str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size, sha256=sha256(p)) for p in sorted(paths)}


def numeric(row):
    return {**{k: sw._field_value(row, k) for k in sw.FIELDS}, sw.WIN5_KEY: sw.parse_window_series(row[sw.WIN5_KEY])}


def digest_rows(path, codes=None):
    h, n = hashlib.sha256(), 0
    with Path(path).open(newline='') as f:
        rows = csv.reader(f)
        header = next(rows)
        i = header.index('security_code')
        h.update((','.join(header) + '\n').encode())
        for row in rows:
            if codes is None or row[i] in codes:
                h.update((','.join(row) + '\n').encode()); n += 1
    return dict(sha256=h.hexdigest(), rows=n)


def build_subset(src, codes, dest):
    """One streaming pass: write the panel-code subset and digest the same production rows."""
    h, n = hashlib.sha256(), 0
    with Path(src).open(newline='') as f, Path(dest).open('w', newline='') as g:
        rows, w = csv.reader(f), csv.writer(g, lineterminator='\n')
        header = next(rows)
        i = header.index('security_code')
        w.writerow(header); h.update((','.join(header) + '\n').encode())
        for row in rows:
            if row[i] in codes:
                w.writerow(row); h.update((','.join(row) + '\n').encode()); n += 1
    return dict(sha256=h.hexdigest(), rows=n)


def restore_reference(manifest_inputs, into):
    """Research copies of the reference tables at the registered hashes (from git history); live files are never rewritten."""
    into.mkdir(parents=True, exist_ok=True)
    out, origin = {}, {}
    for name in REFERENCE_INPUTS:
        want = manifest_inputs[name]['sha256']
        if sha256(ROOT / name) == want:
            out[name], origin[name] = ROOT / name, 'live'
            continue
        for commit in subprocess.check_output(['git', 'log', '-60', '--format=%H', '--', name], cwd=ROOT, text=True).splitlines():
            blob = subprocess.check_output(['git', 'show', f'{commit}:{name}'], cwd=ROOT)
            if hashlib.sha256(blob).hexdigest() == want:
                q = into / Path(name).name
                q.write_bytes(blob); out[name], origin[name] = q, commit
                break
        assert name in out, f'registered version of {name} not found in git history'
    return out, origin


def prepare():
    previous = json.loads((REF / 'manifest.json').read_text())
    assert sw.BASE == previous['base'] and sw.DEFAULT_STARTS == previous['starts']
    for code, end in previous['price_ends'].items():
        with (ROOT / f'data/raw/ohlcv/{code}.csv').open('rb') as f:
            header = f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0, 2); f.seek(max(0, f.tell() - 4096)); last = f.read().decode().splitlines()[-1].split(',')
        assert last[header.index('date')] == end, code
    # 在册批次的状态子集必须原样存在
    old_states = [v for v in previous['state_args'] if v.endswith('.csv')]
    for p in old_states:
        assert sha256(ROOT / p) == previous['inputs'][p]['sha256'], p
    ref_frozen, ref_origin = restore_reference(previous['inputs'], EXP / 'raw' / 'frozen_ref')
    cur_dir = EXP / 'raw' / 'frozen_current'; cur_dir.mkdir(parents=True, exist_ok=True)
    cur_frozen = {}
    for name in REFERENCE_INPUTS:
        q = cur_dir / Path(name).name
        shutil.copyfile(ROOT / name, q); cur_frozen[name] = q
    # 当前生产逐日状态的面板子集（与 OI-168 批次相同代码集），逐行 digest 与生产一致
    codes = set((WC / 'codes.txt').read_text().split())
    args = shlex.split(sw.BASE)
    (EXP / 'states').mkdir(exist_ok=True)
    equivalence, new_state_args, subset_changed = [], [], {}
    for side, opt in (('base', '--daily-states'), ('hold', '--hold-states')):
        prod = ROOT / args[args.index(opt) + 1]
        dest = EXP / 'states' / f'states_{side}.csv'
        prod_digest = build_subset(prod, codes, dest)
        sub_digest = digest_rows(dest)
        assert prod_digest == sub_digest, (side, prod_digest, sub_digest)
        old = digest_rows(ROOT / old_states[0 if side == 'base' else 1])
        equivalence.append(dict(side=side, subset=sub_digest, production=prod_digest, registered_subset=old))
        subset_changed[side] = old != sub_digest
        new_state_args += [opt, str(dest.relative_to(ROOT))]
    import backtest_valuation_strategy as bt
    panel_codes = {c for _, members in bt.load_universe(ROOT / args[args.index('--universe-file') + 1]) for c in members}
    assert panel_codes <= codes
    paths = {ROOT / p for p in previous['inputs'] if (ROOT / p).exists()}
    now = fingerprint(paths)
    changed = sorted(p for p, v in now.items() if v != previous['inputs'][p])
    assert 'scripts/backtest_valuation_strategy.py' in changed and 'scripts/sweep_backtest_configs.py' in changed
    paths |= {EXP / p for p in ('run.py', 'engine.py', 'preregister.md', 'register.py')}
    paths |= {ROOT / 'scripts/slurm/oi167_land_20260913.sbatch', ROOT / 'scripts/test_position_cap_lot.py'}
    paths |= set(ref_frozen.values()) | set(cur_frozen.values()) | {EXP / 'states' / f'states_{s}.csv' for s in ('base', 'hold')}
    manifest = dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), job_id=os.environ.get('SLURM_JOB_ID'),
                    base=sw.BASE, starts=sw.DEFAULT_STARTS, metric=sw.METRIC_VERSION, inputs=fingerprint(paths),
                    changed_since_reference=changed, reference='exp_c030r35_land_20260910',
                    guard_state_args=previous['state_args'], guard_reference_inputs={k: str(v.relative_to(ROOT)) for k, v in ref_frozen.items()},
                    guard_reference_origin=ref_origin,
                    registration_state_args=new_state_args, registration_reference_inputs={k: str(v.relative_to(ROOT)) for k, v in cur_frozen.items()},
                    state_subset_equivalence=equivalence, state_subset_changed_since_registration=subset_changed,
                    price_ends=previous['price_ends'])
    save('manifest.json', manifest)
    print(f'PREPARE COMPLETE: reference tables restored {ref_origin}; state subset changed {subset_changed}', flush=True)
    return manifest


def one(job):
    group, start, excluded, manifest = job
    tag = sw.summary_tag('BASE', start, ','.join(excluded))
    out = EXP / 'cache' / group; out.mkdir(parents=True, exist_ok=True)
    error = EXP / 'errors' / f'{group}_{tag}.txt'; error.parent.mkdir(exist_ok=True)
    guard = group.startswith('guard')
    states = manifest['guard_state_args' if guard else 'registration_state_args']
    refs = manifest['guard_reference_inputs' if guard else 'registration_reference_inputs']
    cmd = [sys.executable, str(EXP / 'engine.py'), *shlex.split(manifest['base']), *states, '--since', start,
           '--label-suffix', '_' + tag, '--out-dir', str(out), '--equity-bond-log-dir', str(EXP / 'daily' / group),
           '--equity-bond-data', refs['data/reference/equity_bond_csi300.csv']]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    env = dict(os.environ, RAYKEY_GROUP=group, RAYKEY_ACTIONS=str(ROOT / refs['data/raw/corporate_actions/a_share_corporate_actions.csv']),
               RAYKEY_RATES=str(ROOT / refs['data/reference/cost_of_equity_inputs.csv']))
    summary, stats_file = out / f'summary_{tag}.csv', EXP / 'stats' / group / f'{tag}.json'
    if not (summary.exists() and stats_file.exists() and (EXP / 'nav' / group / f'{tag}.csv').exists()):   # 续跑：已完成路径不重算
        with error.open('w') as f:
            subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=env, check=True)
    row = next(r for r in read(summary) if r['策略'].startswith('trend_'))
    stats = json.loads((EXP / 'stats' / group / f'{tag}.json').read_text())
    return dict(group=group, arm='BASE', start=start, nav_tag=tag, guard_skips=stats.get(GUARD_STAT, 0), **row)


def run_group(group, excluded, manifest, workers):
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in as_completed([pool.submit(one, (group, s, excluded, manifest)) for s in sw.DEFAULT_STARTS]):
            rows.append(f.result()); print(f'{group} {len(rows)}/14', flush=True)
    rows.sort(key=lambda r: r['start'])
    return rows


def check_complete(rows):
    assert {r['start'] for r in rows} == set(sw.DEFAULT_STARTS)
    for r in rows:
        assert r['计量版本'] == sw.METRIC_VERSION and int(r['负现金日数']) == 0
        assert '_cap0.6s_' in r['策略'], r['策略']
        nav = read(EXP / 'nav' / r['group'] / f"{r['nav_tag']}.csv")
        assert nav[0]['date'] == r['首个净值日'] and nav[-1]['date'] == r['末次净值日']
        months = {x['date'][:7] for x in nav if x['date'][:7] < nav[-1]['date'][:7]}
        number = lambda m: int(m[:4]) * 12 + int(m[5:7]) - 1
        numbers = {number(m) for m in months}
        expected = {m for m in months if number(m) - 60 in numbers}
        series = sw.parse_window_series(r[sw.WIN5_KEY])
        assert set(series) == expected and all(math.isfinite(v) for v in series.values())
        assert all(float(x['cash']) >= -1e-6 for x in nav)


def path_deltas(new_rows, ref_rows, label):
    out, identical = [], 0
    for r in new_rows:
        o = ref_rows[r['start']]
        n, b = numeric(r), numeric(o)
        same = all(n[k] == b[k] for k in sw.FIELDS if k != '策略') and n[sw.WIN5_KEY] == b[sw.WIN5_KEY]
        identical += same
        out.append(dict(comparison=label, start=r['start'], identical=same, guard_skips=r.get('guard_skips', ''),
                        d_cagr_pp=100 * (n['年化'] - b['年化']), d_win5_pp=100 * sw.start_delta(n, b, sw.WIN5_KEY),
                        d_mdd_pp=100 * (n['最大回撤'] - b['最大回撤']), d_p25_pp=100 * (n['滚动5年年化P25'] - b['滚动5年年化P25']),
                        d_roll5dd_pp=100 * (n['滚动5年回撤中位'] - b['滚动5年回撤中位']), neg_flip=sw.neg_window_flip(n, b),
                        d_turnover=n['年均换手'] - b['年均换手'], d_exposure_pp=100 * (n['平均仓位'] - b['平均仓位']),
                        buys_new=float(r['买入笔数']), buys_ref=float(o['买入笔数'])))
    return out, identical


def sweep_text(blocks, fixed):
    text = sw.metric_header() + '\n#MARKET|a\n#EX5|fixed|' + ','.join(fixed) + '\n'
    for label, rows in blocks:
        for r in rows:
            text += '|'.join([label, r['start']] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n'
            text += f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n"
    return text


def report(sweep_name, report_name, title):
    with (EXP / report_name).open('w') as f, contextlib.redirect_stdout(f):
        sw.report(EXP / sweep_name, title)
    rp = EXP / report_name
    rp.write_text('\n'.join(x.rstrip() for x in rp.read_text().splitlines()) + '\n')


def main():
    p = argparse.ArgumentParser(); p.add_argument('--workers', type=int, default=12); args = p.parse_args()
    assert args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', args.workers))
    manifest = prepare()
    ref_rows = {(r['group'], r['start']): r for r in read(REF / 'summary_rows.csv') if r['arm'] == 'BASE' and r['group'] in ('full', 'A')}
    old_a = sorted(ref_rows['full', sw.EX5_ANCHOR_START][sw.EX5_FIELD].split('/'))
    # ---- 护栏：在册输入 + 新引擎
    g_full = run_group('guard_full', [], manifest, args.workers); check_complete(g_full)
    g_a = run_group('guard_A', old_a, manifest, args.workers); check_complete(g_a)
    d_full, id_full = path_deltas(g_full, {s: ref_rows['full', s] for s in sw.DEFAULT_STARTS}, 'guard_full_vs_registered')
    d_a, id_a = path_deltas(g_a, {s: ref_rows['A', s] for s in sw.DEFAULT_STARTS}, 'guard_A_vs_registered')
    arms_full = {'BASE': {s: numeric(ref_rows['full', s]) for s in sw.DEFAULT_STARTS}, 'OI167': {r['start']: numeric(r) for r in g_full}}
    arms_a = {'BASE': {s: numeric(ref_rows['A', s]) for s in sw.DEFAULT_STARTS}, 'OI167': {r['start']: numeric(r) for r in g_a}}
    verdict, reasons, vals = sw.adoption_verdict(arms_full, arms_a, 'OI167')
    gate_hit = any(r.startswith(('闸门', '否决')) for r in reasons)
    main_lo, comp_lo = min(vals['主读数']), min(vals['复利读数'])
    track_a = (not gate_hit and verdict != '不可判' and main_lo >= -sw.RULING_TOLERANCE and comp_lo >= -sw.RULING_TOLERANCE)
    guard = dict(verdict=verdict, reasons=reasons, main_delta=vals['主读数'], compound_delta=vals['复利读数'], mdd_delta=vals['ΔMDD'],
                 worst5_delta=vals['Δ滚5最差'], gate_or_veto=gate_hit, track_a_pass=track_a,
                 identical_paths=id_full + id_a, changed_paths=28 - id_full - id_a,
                 guard_skips_total=sum(r['guard_skips'] for r in g_full + g_a), winners_reference=old_a)
    (EXP / 'sweep_guardrail.txt').write_text(sweep_text(
        [('BASE', [ref_rows['full', s] for s in sw.DEFAULT_STARTS]), ('OI167', g_full),
         ('EX5:BASE', [ref_rows['A', s] for s in sw.DEFAULT_STARTS]), ('EX5:OI167', g_a)], old_a))
    report('sweep_guardrail.txt', 'report_guardrail.txt', 'OI-167 护栏：新引擎 BASE（OI167）对在册 BASE 配对（在册输入）')
    # ---- 登记：当前生产输入 + 新引擎；A = 本次 BASE 自身赢家
    r_full = run_group('full', [], manifest, args.workers); check_complete(r_full)
    new_a = sorted(next(r for r in r_full if r['start'] == sw.EX5_ANCHOR_START)[sw.EX5_FIELD].split('/'))
    r_a = run_group('A', new_a, manifest, args.workers); check_complete(r_a)
    d_in, id_in = path_deltas(r_full, {r['start']: r for r in g_full}, 'registration_full_vs_guard_full')   # 同引擎，只差输入
    guard.update(winners_new=new_a, inputs_effect_identical_paths=id_in)
    save('guardrail.json', guard)
    write('path_deltas.csv', d_full + d_a + d_in)
    (EXP / 'sweep_base.txt').write_text(sweep_text([('BASE', r_full), ('EX5:BASE', r_a)], new_a))
    report('sweep_base.txt', 'report_sweep_base.txt', 'OI-167 整手守卫后生产 BASE 在册重登')
    register = {}
    for g, rows in (('full', r_full), ('A', r_a)):
        register[g] = {k: st.median(sw._field_value(r, k) for r in rows) for k in sw.FIELDS}
        register[g]['长跑'] = {s: {k: float(next(r for r in rows if r['start'] == s)[k]) for k in ('年化', '最大回撤')}
                              for s in ('2009-11-01', '2011-11-01')}
    save('in_register.json', register)
    write('summary_rows.csv', g_full + g_a + r_full + r_a)
    actual = fingerprint({ROOT / p for p in manifest['inputs']})
    unchanged = all(v == manifest['inputs'][p] for p, v in actual.items())
    assert unchanged
    save('verification.json', dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), job_id=manifest['job_id'],
         guard_paths=28, base_paths=28, identical_paths=guard['identical_paths'], changed_paths=guard['changed_paths'],
         track_a_pass=track_a, verdict=verdict, negative_cash_days=0, complete_start_and_window_sets=True,
         inputs_unchanged=unchanged, winners_unchanged=new_a == old_a, strategy_marker='_cap0.6s_',
         state_subset_changed_since_registration=manifest['state_subset_changed_since_registration']))
    print(f"LAND VERIFICATION COMPLETE: guard identical {guard['identical_paths']}/28; verdict {verdict}; track-A pass {track_a}", flush=True)


if __name__ == '__main__':
    main()

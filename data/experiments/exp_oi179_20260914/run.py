"""All preregistered full/A/U paths for the 6-arm slope comparison, with BASE reproduction against the landed OI-167 BASE."""
import argparse
import csv
import contextlib
import statistics as st
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from prepare import EXP, ROOT, LAND, fingerprint, save, sw


def one(job):
    group, arm, start, excluded, states, resume = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cache = EXP / 'cache' / group
    cache.mkdir(parents=True, exist_ok=True)
    summary = cache / f'summary_{tag}.csv'
    if not resume or not summary.exists():
        refs = json.loads((EXP / 'manifest.json').read_text())['frozen_reference_inputs' if group.startswith('guard') else 'current_reference_inputs']
        command = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), *states,
                   '--slope-arm', arm, '--since', start, '--label-suffix', '_' + tag,
                   '--out-dir', str(cache), '--equity-bond-log-dir', str(EXP / 'daily' / group),
                   '--equity-bond-data', refs['data/reference/equity_bond_csi300.csv']]
        if group == 'full' and arm in ('BASE', 'BOTH1') and start in ('2009-11-01', '2011-11-01'):
            if '--no-artifacts' in command:
                command.remove('--no-artifacts')
            output = EXP / 'signals' / arm / start
            output.mkdir(parents=True, exist_ok=True)
            command += ['--candidate-log', str(output / 'candidates.csv'), '--trade-log', str(output / 'ledger.csv')]
        if excluded:
            command += ['--exclude-codes', ','.join(excluded)]
        env = dict(os.environ, RAYKEY_ACTIONS=str(ROOT / refs['data/raw/corporate_actions/a_share_corporate_actions.csv']),
                   RAYKEY_RATES=str(ROOT / refs['data/reference/cost_of_equity_inputs.csv']))
        error = EXP / 'errors' / f'{tag}.txt'
        error.parent.mkdir(exist_ok=True)
        with error.open('w') as f:
            result = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=env)
        if result.returncode:
            raise RuntimeError(f'{tag} exit {result.returncode}: {error.read_text()[-3000:]}')
    with summary.open() as f:
        row = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION
    assert row['负现金日数'] == '0', (tag, row['负现金日数'])
    assert (EXP / 'nav' / f'{tag}.csv').exists()
    return dict(group=group, arm=arm, start=start, nav_tag=tag, **row)


def batch(group, arms, excluded, args, manifest):
    jobs = [(group, arm, start, excluded, manifest['state_args'], args.resume) for arm in arms for start in sw.DEFAULT_STARTS]
    rows = []
    print(f'{group} START {len(jobs)} paths, excluded={excluded}', flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed([pool.submit(one, j) for j in jobs]):
            rows.append(f.result())
            if len(rows) % 28 == 0:
                print(f'{group} {len(rows)}/{len(jobs)}', flush=True)
    rows.sort(key=lambda r: (arms.index(r['arm']), r['start']))
    with (EXP / f'sweep_{group}.txt').open('w') as f:
        f.write(sw.metric_header() + '\n#MARKET|a\n')
        if excluded:
            f.write('#EX5|fixed|' + ','.join(excluded) + '\n')
        for row in rows:
            label = ('EX5:' if excluded else '') + row['arm']
            f.write('|'.join([label, row['start']] + [f'{sw._field_value(row, k):.6f}' for k in sw.FIELDS]) + '\n')
            f.write(f"#WIN5|{label}|{row['start']}|{row[sw.WIN5_KEY]}\n")
    return rows


def write_rows(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def numeric(row):
    return {**{k: sw._field_value(row, k) for k in sw.FIELDS}, sw.WIN5_KEY: sw.parse_window_series(row[sw.WIN5_KEY])}


def guardrail(rows, old_a):
    groups = {}
    changes = []
    for group in ('guardfull', 'guardA'):
        groups[group] = {a: {r['start']: numeric(r) for r in rows if r['group'] == group and r['arm'] == a}
                         for a in ('LEGACY', 'BASE')}
        n, b = groups[group]['BASE'], groups[group]['LEGACY']
        assert not sw.pairing_defects(groups[group], 'BASE', 'LEGACY', sw.DEFAULT_STARTS, group)
        for start in sw.DEFAULT_STARTS:
            changes.append(dict(group=group, start=start,
                cagr_pp=100 * sw.start_delta(n[start], b[start], '年化'),
                P_pp=100 * sw.start_delta(n[start], b[start], sw.WIN5_KEY),
                mdd_pp=100 * sw.start_delta(n[start], b[start], '最大回撤'),
                roll5dd_pp=100 * sw.start_delta(n[start], b[start], '滚动5年回撤中位'),
                negative_flip=sw.neg_window_flip(n[start], b[start])))
    metrics = {g: {k: st.median(r[k] for r in changes if r['group'] == g)
                   for k in ('cagr_pp', 'P_pp', 'mdd_pp', 'roll5dd_pp')} for g in groups}
    flips = sum(r['negative_flip'] for r in changes if r['group'] == 'guardfull')
    full = metrics['guardfull']
    passed = full['cagr_pp'] >= -1 and full['P_pp'] >= -1 and full['roll5dd_pp'] <= 3 and flips <= len(sw.DEFAULT_STARTS)/2
    new_a = sorted(next(r for r in rows if r['group'] == 'guardfull' and r['arm'] == 'BASE'
                        and r['start'] == sw.EX5_ANCHOR_START)['前五赢家'].split('/'))
    save('guardrail.json', dict(track_a_pass=passed, paired=metrics, negative_flips=flips,
                               old_winners=old_a, corrected_winners=new_a))
    write_rows('guard_paired.csv', changes)
    out = sw.metric_header() + '\n#MARKET|a\n#EX5|fixed|' + ','.join(old_a) + '\n'
    for r in rows:
        if r['group'] not in groups: continue
        label = ('EX5:' if r['group'] == 'guardA' else '') + ('BASE' if r['arm'] == 'LEGACY' else 'FIX')
        out += '|'.join([label, r['start']] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n'
        out += f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n"
    (EXP/'guard_sweep.txt').write_text(out)
    with (EXP/'guard_report.txt').open('w') as f, contextlib.redirect_stdout(f):
        sw.report(EXP/'guard_sweep.txt', 'OI-179机制修复护栏（轨道A判定见guardrail.json）')
    rp = EXP/'guard_report.txt'; rp.write_text('\n'.join(x.rstrip() for x in rp.read_text().splitlines())+'\n')
    return passed, new_a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=48)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--smoke', action='store_true')
    args = ap.parse_args()
    assert args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', args.workers))
    manifest = json.loads((EXP/'manifest.json').read_text())
    assert manifest['base'] == sw.BASE and manifest['starts'] == sw.DEFAULT_STARTS
    assert fingerprint({ROOT/p for p in manifest['inputs']}) == manifest['inputs']
    # A new manifest cannot reuse paths from a different input snapshot.
    import hashlib
    signature = hashlib.sha256(json.dumps(manifest['inputs'], sort_keys=True).encode()).hexdigest()
    marker = EXP/'cache_signature.txt'
    if marker.exists(): assert marker.read_text().strip() == signature, 'Cache input signature changed; use a new batch.'
    else: marker.write_text(signature+'\n')
    old = sw.load_scan(LAND/'sweep_base.txt')[0]
    old_a = sorted(json.loads((LAND/'guardrail.json').read_text())['winners_new'])
    if args.smoke:
        import time
        began = time.monotonic()
        rows = [one(('guardfull', a, sw.EX5_ANCHOR_START, [], manifest['state_args'], False)) for a in ('LEGACY', 'BASE')]
        for k in sw.FIELDS:
            assert float(f'{sw._field_value(rows[0], k):.6f}') == old['']['BASE'][sw.EX5_ANCHOR_START][k], k
        save('smoke.json', dict(job_id=os.getenv('SLURM_JOB_ID'), seconds=time.monotonic()-began,
                               legacy_fields_reproduced=len(sw.FIELDS), rows=[dict(arm=r['arm'], cagr=r['年化']) for r in rows]))
        print('SMOKE COMPLETE: old BASE reproduced, fixed engine completed.', flush=True)
        return
    guards = batch('guardfull', ['LEGACY','BASE'], [], args, manifest) + batch('guardA', ['LEGACY','BASE'], old_a, args, manifest)
    checked = 0
    for r in guards:
        if r['arm'] != 'LEGACY': continue
        b = old['' if r['group'] == 'guardfull' else 'EX5:']['BASE'][r['start']]
        for k in sw.FIELDS:
            assert float(f'{sw._field_value(r,k):.6f}') == b[k], (r['group'],r['start'],k)
            checked += 1
        assert sw.parse_window_series(r[sw.WIN5_KEY]) == b[sw.WIN5_KEY]
    passed, fixed_a = guardrail(guards, old_a)
    if fixed_a != old_a:
        guards += batch('guardU', ['LEGACY','BASE'], sorted(set(old_a)|set(fixed_a)), args, manifest)
    write_rows('guard_summary_rows.csv', guards)
    # Continue the authorized diagnosis even if a guardrail fails; registration separately requires a pass.
    labels = [r['arm'] for r in json.loads((EXP/'grid.json').read_text())]
    full = batch('full', labels, [], args, manifest)
    a = sorted(next(r for r in full if r['arm']=='BASE' and r['start']==sw.EX5_ANCHOR_START)['前五赢家'].split('/'))
    rows = full + batch('A', labels, a, args, manifest)
    unions, winners, union_groups = {}, {}, {}
    for arm in labels[1:]:
        b = sorted(next(r for r in full if r['arm']==arm and r['start']==sw.EX5_ANCHOR_START)['前五赢家'].split('/'))
        u = tuple(sorted(set(a)|set(b)))
        unions.setdefault(u, []).append(arm)
        winners[arm] = dict(A=a, B=b, U=list(u))
    save('winner_sets.json', winners)
    executed = len(guards) + len(rows)
    for i, (u, candidates) in enumerate(unions.items(), 1):
        g = f'U{i}'; reuse = list(u) == a
        if reuse:
            new = [dict(r, group=g) for r in rows if r['group']=='A' and r['arm'] in ['BASE',*candidates]]
        else:
            new = batch(g, ['BASE',*candidates], list(u), args, manifest); executed += len(new)
        rows += new
        union_groups[g] = dict(codes=list(u), candidates=candidates, reused_A=reuse)
    write_rows('summary_rows.csv', rows)
    unchanged = fingerprint({ROOT/p for p in manifest['inputs']}) == manifest['inputs']
    assert unchanged
    save('verification.json', dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        job_id=os.getenv('SLURM_JOB_ID'), inputs_unchanged=unchanged, baseline_values_checked=checked,
        baseline_paths=28, baseline_windows_identical=True, executed_paths=executed, summary_rows=len(rows),
        track_a_pass=passed, union_groups=union_groups, current_winners=a))
    print(f'COMPLETE {executed} executed paths, track A pass={passed}, legacy checks={checked}', flush=True)


if __name__ == '__main__': main()


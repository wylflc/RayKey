"""Read-only current-BASE attribution and lagged risk-indicator diagnostics."""
import ast
import bisect
import collections
import contextlib
import csv
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import shlex
import statistics as st
import subprocess
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
REF = EXP.parent / 'exp_c030r35_land_20260910'
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'scripts/experimental')]
import backtest_valuation_strategy as bt
import sweep_backtest_configs as sw
from drawdown_path import episodes


def read(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write(name, rows):
    with (EXP/name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def exposure(r):
    return 1 + (float(r['debt'])-float(r['cash']))/float(r['net_equity'])


def replay(tag, manifest, frozen):
    """Insert one observer in memory at day end, without changing the engine file."""
    target = EXP/'raw'/tag
    target.mkdir(parents=True, exist_ok=True)
    original_run, original_summary = bt.run, bt.summarize
    original_actions, original_rates = bt.ACTIONS, bt.RATES
    bt.ACTIONS = frozen.get('data/raw/corporate_actions/a_share_corporate_actions.csv', bt.ACTIONS)
    bt.RATES = frozen.get('data/reference/cost_of_equity_inputs.csv', bt.RATES)
    previous_contrib = {}
    holding_rows, pnl_rows = [], []
    curve = []

    def capture(day, portfolio, marks, contrib, eq_prev, mas):
        for code, total in contrib.items():
            delta = total-previous_contrib.get(code, 0.0)
            if delta:
                pnl_rows.append(dict(date=day, code=code, pnl=delta*eq_prev))
        previous_contrib.clear(); previous_contrib.update(contrib)
        for code, lot in portfolio.lots.items():
            p = marks.get(code, 0.0)
            ma = mas.get(code, {}).get(day, {})
            holding_rows.append(dict(date=day, code=code, shares=lot.shares, price=p,
                market_value=lot.shares*p, ma20=ma.get(20, ''), ma60=ma.get(60, ''),
                entry_stop=lot.entry_stop, avg_cost=lot.avg_cost))

    tree = ast.parse(inspect.getsource(original_run))
    matches = 0
    for node in ast.walk(tree):
        for _, value in ast.iter_fields(node):
            if not isinstance(value, list):
                continue
            for i, stmt in list(enumerate(value)):
                if (isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and
                    t.id == 'weights' for t in stmt.targets)):
                    value.insert(i, ast.parse('_dd_capture(day, portfolio, marks, contrib, eq_prev, mas)').body[0])
                    matches += 1
    assert matches == 1, matches
    bt.__dict__['_dd_capture'] = capture
    exec(compile(ast.fix_missing_locations(tree), '<read-only drawdown observer>', 'exec'), bt.__dict__)

    def summarize(name, result, *args):
        if name.startswith('trend_'):
            curve.extend(result['equity'])
        return original_summary(name, result, *args)

    bt.summarize = summarize
    args = [*shlex.split(sw.BASE), *manifest['state_args'], '--since',
        f'{tag[4:8]}-{tag[8:10]}-{tag[10:12]}', '--label-suffix', '_'+tag,
        '--out-dir', str(target), '--trade-log', str(target/'ledger.csv')]
    if 'data/reference/equity_bond_csi300.csv' in frozen:
        args += ['--equity-bond-data', str(frozen['data/reference/equity_bond_csi300.csv'])]
    oldargv = sys.argv
    try:
        sys.argv = [str(ROOT/'scripts/backtest_valuation_strategy.py'), *args]
        with (target/'run.log').open('w') as f, contextlib.redirect_stdout(f):
            bt.main()
    finally:
        sys.argv = oldargv
        bt.run, bt.summarize = original_run, original_summary
        bt.ACTIONS, bt.RATES = original_actions, original_rates
        bt.__dict__.pop('_dd_capture', None)
    ref = read(REF/'nav'/f'{tag}.csv')
    assert len(ref) == len(curve)
    for actual, expected in zip(curve, ref):
        assert actual[0] == expected['date']
        # The engine's initial capital row predates the two concentration columns.
        for value, name in zip(actual[1:], ('net_equity','cash','positions','debt',
                                          'margin_ratio','top1_weight','top3_weight')):
            assert float(value) == float(expected[name]), (tag, actual[0], name)
    write(f'raw/{tag}/holdings.csv', holding_rows)
    write(f'raw/{tag}/pnl.csv', pnl_rows)
    return dict(tag=tag, exact_nav_rows=len(curve), holdings_rows=len(holding_rows),
                pnl_rows=len(pnl_rows), engine_file_unchanged=True)


def sustained(flags, n=3):
    out, streak = [], 0
    for flag in flags:
        streak = streak+1 if flag else 0
        out.append(streak >= n)
    return out


def main():
    manifest = json.loads((REF/'manifest.json').read_text())
    assert manifest['base'] == sw.BASE and manifest['starts'] == sw.DEFAULT_STARTS
    # Verify all market/state/action inputs inherited from the landing manifest.
    verified, frozen, recovered = {}, {}, {}
    (EXP/'raw/frozen').mkdir(parents=True, exist_ok=True)
    # Explicit frozen subset arguments override these live production paths, just
    # as in the original landing run. Their current contents are not consumed.
    replaced_paths = {'data/processed/a_share_daily_states_adopted.csv',
                      'data/processed/a_share_daily_states_hold.csv'}
    consumed = {v for v in manifest['state_args'] if v.endswith('.csv')} | {
        'data/processed/pit_attention/panel_moat_bank_v6b.csv',
        'data/processed/a_share_watchlist_quality_tiers.csv',
        'data/processed/entity_reset_dates.csv',
        'data/raw/a_share_securities.csv', 'data/raw/a_share_delisted_roster.csv',
        'data/raw/corporate_actions/a_share_corporate_actions.csv',
        'data/reference/equity_bond_csi300.csv', 'data/reference/cost_of_equity_inputs.csv'}
    assert consumed <= set(manifest['inputs']), consumed-set(manifest['inputs'])
    for name, meta in manifest['inputs'].items():
        if name in consumed or name.startswith('data/raw/ohlcv/'):
            p = ROOT/name
            if p.suffix in ('.csv', '.json'):
                actual = digest(p)
                if actual != meta['sha256']:
                    # Restore a research copy only, never overwrite live inputs.
                    commits = subprocess.check_output(['git','log','-30','--format=%H','--',name],
                                                       cwd=ROOT,text=True).splitlines()
                    for commit in commits:
                        blob = subprocess.check_output(['git','show',f'{commit}:{name}'], cwd=ROOT)
                        if hashlib.sha256(blob).hexdigest() == meta['sha256']:
                            q = EXP/'raw/frozen'/Path(name).name
                            q.write_bytes(blob); frozen[name] = q
                            recovered[name] = dict(commit=commit, sha256=meta['sha256'])
                            actual = digest(q)
                            break
                    assert actual == meta['sha256'], name
                verified[name] = actual
    engine_hash = digest(ROOT/'scripts/backtest_valuation_strategy.py')
    (EXP/'raw').mkdir(exist_ok=True)
    checks = []
    for tag in ('BASE20091101', 'BASE20111101'):
        checks.append(replay(tag, manifest, frozen))
        print('REPLAY VERIFIED', checks[-1], flush=True)
    assert digest(ROOT/'scripts/backtest_valuation_strategy.py') == engine_hash

    index = {r['date']: float(r['close']) for r in read(ROOT/'data/raw/ohlcv/INDEX_000300.csv')}
    idays = sorted(index)
    index_ma = {d: st.mean([index[x] for x in idays[i-119:i+1]])
                for i, d in enumerate(idays) if i >= 119}
    names = {r['security_code']: r['security_name'] for r in read(ROOT/'data/raw/a_share_securities.csv')}
    all_eps, path_mdd, attrib, signals, frequencies, snapshots = [], [], [], [], [], []
    for tag in ['BASE'+s.replace('-', '')+suffix for suffix in ('', 'ex5') for s in sw.DEFAULT_STARTS]:
        nav = read(REF/'nav'/f'{tag}.csv')
        dates = [r['date'] for r in nav]
        byday = {r['date']: r for r in nav}
        eq = [float(r['net_equity']) for r in nav]
        eps = sorted(episodes(list(zip(dates, eq))), key=lambda e: -e[4])
        group = 'A' if tag.endswith('ex5') else 'full'
        eb = {r['date']: r for r in read(REF/'daily'/group/f'_{tag}.csv')}
        returns = [eq[i]/eq[i-1]-1 for i in range(1,len(eq))]
        vol = {dates[i]: st.stdev(returns[i-20:i])*math.sqrt(244) for i in range(20,len(eq))}
        for rank, (peak, peak_eq, trough, trough_eq, dd, recovery) in enumerate(eps, 1):
            if dd < .15:
                continue
            subset = [r for r in nav if peak <= r['date'] <= trough]
            ebr = [eb[r['date']] for r in subset if r['date'] in eb]
            spreads = [float(r['spread']) for r in ebr if r['spread']]
            row = dict(tag=tag, group=group, rank=rank, peak=peak, trough=trough,
                recovery=recovery or '', drawdown=dd, peak_to_trough_sessions=len(subset)-1,
                recovery_sessions=dates.index(recovery)-dates.index(peak) if recovery else '',
                index_same_interval=index[trough]/index[peak]-1 if peak in index and trough in index else '',
                exposure_peak=exposure(byday[peak]), exposure_trough=exposure(byday[trough]),
                exposure_median=st.median([exposure(r) for r in subset]),
                exposure_max=max(exposure(r) for r in subset),
                top1_peak=byday[peak]['top1_weight'], top3_peak=byday[peak]['top3_weight'],
                top3_stock_share_peak=(float(byday[peak]['top3_weight'] or 0)/exposure(byday[peak])
                                      if exposure(byday[peak]) > 0 else ''),
                cap_days=sum(bool(r['cap']) for r in ebr), spread_min=min(spreads) if spreads else '',
                spread_max=max(spreads) if spreads else '', vol20_peak=vol.get(peak, ''),
                vol20_trough=vol.get(trough, ''))
            all_eps.append(row)
            if rank == 1:
                path_mdd.append(row)
        if tag not in ('BASE20091101', 'BASE20111101'):
            continue
        holdings = collections.defaultdict(list)
        for r in read(EXP/'raw'/tag/'holdings.csv'):
            holdings[r['date']].append(r)
        pnls = read(EXP/'raw'/tag/'pnl.csv')
        weak, coverage = {}, {}
        for d, rs in holdings.items():
            total = sum(float(r['market_value']) for r in rs)
            known = sum(float(r['market_value']) for r in rs if r['ma60'])
            bad = sum(float(r['market_value']) for r in rs if r['ma60'] and float(r['price']) < float(r['ma60']))
            weak[d] = bad/total if total else 0
            coverage[d] = known/total if total else 1
        peak_eq, dd_series = 0, []
        for e in eq:
            peak_eq = max(peak_eq, e); dd_series.append(1-e/peak_eq)
        flags = {
            'vol20_gt40_3d': sustained([vol.get(d, 0) > .4 for d in dates]),
            'held_below_ma60_gt50_3d': sustained([weak.get(d, 0) > .5 and coverage.get(d, 0) >= .95 for d in dates]),
            'account_dd_gt10_3d': sustained([x > .1 for x in dd_series]),
            'index_below_ma120_3d': sustained([d in index_ma and index[d] < index_ma[d] for d in dates])}
        for indicator, flags_ in flags.items():
            frequencies.append(dict(tag=tag, indicator=indicator, observation_days=len(dates),
                active_days=sum(flags_), active_fraction=sum(flags_)/len(dates),
                state_entries=sum(v and (i == 0 or not flags_[i-1]) for i,v in enumerate(flags_)),
                holding_ma_coverage_min=min(coverage.values())))
        for rank, (peak, peak_eq, trough, trough_eq, dd, recovery) in enumerate(eps[:7], 1):
            total = collections.defaultdict(float)
            for r in pnls:
                if peak < r['date'] <= trough:
                    total[r['code']] += float(r['pnl'])
            loss = peak_eq-trough_eq
            for code, value in sorted(total.items(), key=lambda x:x[1]):
                attrib.append(dict(tag=tag, rank=rank, peak=peak, trough=trough, code=code,
                    name=names.get(code, code), pnl_over_peak=value/peak_eq, share_of_net_loss=-value/loss))
            residual = trough_eq-peak_eq-sum(total.values())
            attrib.append(dict(tag=tag, rank=rank, peak=peak, trough=trough, code='RESIDUAL',
                name='未分摊费用税息等', pnl_over_peak=residual/peak_eq, share_of_net_loss=-residual/loss))
            assert abs(sum(r['pnl_over_peak'] for r in attrib if r['tag']==tag and r['rank']==rank)+dd) < 1e-10
            for point in (peak, trough):
                for r in sorted(holdings[point], key=lambda r:-float(r['market_value'])):
                    snapshots.append(dict(tag=tag, rank=rank, point='peak' if point==peak else 'trough',
                        name=names.get(r['code'],r['code']), equity_weight=float(r['market_value'])/float(byday[point]['net_equity']), **r))
            pi, ti = dates.index(peak), dates.index(trough)
            for indicator, f in flags.items():
                # Evaluate the peak-day close and later observations; execute next close.
                first = next((i for i in range(pi, ti) if f[i]), None)
                signals.append(dict(tag=tag, rank=rank, peak=peak, trough=trough, indicator=indicator,
                    signal_day=dates[first] if first is not None else '',
                    already_active_at_peak=bool(f[pi]),
                    earliest_execution_close=dates[first+1] if first is not None else '',
                    drawdown_at_execution=1-eq[first+1]/peak_eq if first is not None else '',
                    remaining_base_decline=1-trough_eq/eq[first+1] if first is not None else '',
                    episode_active_fraction=sum(f[pi:ti+1])/(ti-pi+1)))
    for name, rows in [('episodes.csv',all_eps), ('path_max_drawdowns.csv',path_mdd),
                       ('attribution.csv',attrib), ('indicator_timing.csv',signals),
                       ('indicator_frequency.csv',frequencies), ('holding_snapshots.csv',snapshots)]:
        write(name, rows)
    # Independent summary consistency check for every baseline path.
    for r in path_mdd:
        summary = next(x for x in read(ROOT/'data/backtest'/f"summary_{r['tag']}.csv") if x['策略'].startswith('trend_'))
        assert abs(float(summary['最大回撤'])-r['drawdown']) < 1e-12
    verification = dict(job_id=os.environ.get('SLURM_JOB_ID'), replay=checks,
        summary_mdd_paths_verified=len(path_mdd), attribution_reconciled_episodes=14,
        verified_input_hashes=verified, engine_sha256=engine_hash,
        historical_inputs_recovered=recovered,
        live_paths_overridden_by_frozen_state_args=sorted(replaced_paths),
        index_sha256=digest(ROOT/'data/raw/ohlcv/INDEX_000300.csv'),
        readme_sha256=digest(EXP/'README.md'), script_sha256=digest(Path(__file__)),
        first_nav_date='2009-11-02', last_nav_date='2026-08-28', candidate_backtests=0)
    (EXP/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n')
    print('DIAGNOSIS COMPLETE', len(all_eps), 'episodes;', len(path_mdd), 'paths', flush=True)


if __name__ == '__main__':
    main()

"""§12.1 第 10～11 款信号层三表、贡献归因、买入线对齐容差与换仓尺度漂移（NEW 对同输入对照）；不调参。"""
import contextlib
import os
import shlex
import statistics as st
import subprocess
import sys
from collections import defaultdict

from common import EXP, PANEL, ROOT, load, read, save
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw
import selection_edge_audit as edge
import align_buy_line as align
import check_swap_margin_scale_drift as drift

REGISTERED_SHARE = 0.17771


def run_report(name, script, args):
    with (EXP / name).open('w') as out:
        subprocess.run([sys.executable, str(ROOT / 'scripts/experimental' / script), *map(str, args)],
                       cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)


def main():
    control = load('verification.json')['control']
    arms = (control, 'NEW')
    scales = load('align_check.json')['arms']          # 由 align_check.py 在回测前算出
    drift.CAND_STATES = EXP / 'states/NEW/a_share_daily_states_adopted.csv'
    drift.HOLD_STATES = EXP / 'states/NEW/a_share_daily_states_hold.csv'; drift.PANEL = PANEL
    sys.argv = ['scale']
    with (EXP / 'scale_drift.txt').open('w') as out, contextlib.redirect_stdout(out):
        drift_code = drift.main()
    signals = {}
    original = edge.print_block
    for arm in arms:
        signals[arm] = {}

        def capture(title, result, note='', arm=arm):
            signals[arm][title.split()[0] + title.split()[1]] = result
            return original(title, result, note)
        edge.print_block = capture
        sys.argv = ['edge', '--candidate-log', str(EXP / f'candidates_{arm}.csv'), '--trade-log', str(EXP / f'ledger_{arm}.csv')]
        with (EXP / f'selection_{arm}.txt').open('w') as out, contextlib.redirect_stdout(out):
            assert edge.main() == 0
        states = EXP / 'states' / arm
        run_report(f'pv_forward_{arm}.txt', 'panel_tier_forward.py', [
            '--states', states / 'a_share_daily_states_adopted.csv', '--panel', PANEL, '--since', sw.EX5_ANCHOR_START,
            '--ohlcv-dir', ROOT / 'data/raw/ohlcv', '--actions', EXP / 'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'])
        for tol in (.04, .10, .15):
            run_report(f'swap_{arm}_{tol:.2f}.txt', 'swap_regime_control.py', [
                '--candidate-log', EXP / f'candidates_{arm}.csv', '--trade-log', EXP / f'ledger_{arm}.csv',
                '--states', states / 'a_share_daily_states_adopted.csv', '--hold-states', states / 'a_share_daily_states_hold.csv',
                '--panel', PANEL, '--since', sw.EX5_ANCHOR_START, '--tol', tol])
    edge.print_block = original
    paired = {}
    for label in signals[control]:
        values = {a: dict(zip(signals[a][label].get('days', []), signals[a][label].get('diffs', []))) for a in arms}
        common = sorted(values[control].keys() & values['NEW'].keys())
        deltas = {d: values['NEW'][d] - values[control][d] for d in common}
        years = defaultdict(list)
        for d, v in deltas.items():
            years[d[:4]].append(v)
        ym = {y: st.median(v) for y, v in years.items()}
        paired[label] = dict(common_days=len(common), control_days=len(values[control]), new_days=len(values['NEW']),
                             median_delta=st.median(deltas.values()) if deltas else None,
                             positive_days=sum(v > 0 for v in deltas.values()), yearly_medians=ym,
                             positive_years=sum(v > 0 for v in ym.values()),
                             note='共同覆盖日的配对差；重叠日与股票×日期行不是独立样本')
    save('signal_pairs.json', paired)
    rows = read(EXP / 'summary_rows.csv')
    anchors = {a: next(r for r in rows if r['arm'] == a and r['group'] == 'full' and r['start'] == sw.EX5_ANCHOR_START) for a in arms}
    trades = {a: EXP / f"contrib_{r['tag']}_trades.csv" for a, r in anchors.items()}
    run_report('attribution.txt', 'delta_attribution.py', ['--base', trades[control], '--arm', trades['NEW']])
    index = read(ROOT / 'data/backtest/scan_arms_index.csv')
    save('diagnostics_validation.json', dict(job_id=os.getenv('SLURM_JOB_ID'), control=control, drift_exit=drift_code,
                                             buy_line=scales, signals=paired, registered_arm_rows=len(index),
                                             no_parameter_changes=True))


if __name__ == '__main__':
    main()

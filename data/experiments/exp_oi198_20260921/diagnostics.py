"""Required signal/attribution/scale diagnostics; no strategy parameter tuning."""
import contextlib
import csv
import json
import os
import shlex
import statistics as st
import subprocess
import sys
from collections import defaultdict
from prepare import EXP, ROOT, read, save

sys.path.insert(0, str(ROOT/'scripts/experimental'))
import sweep_backtest_configs as sw
import selection_edge_audit as edge
import align_buy_line as align
import check_swap_margin_scale_drift as drift


def run_report(name, script, args):
    with (EXP/name).open('w') as out:
        subprocess.run([sys.executable, str(ROOT/'scripts/experimental'/script), *map(str,args)],
                       cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)


def main():
    panel = EXP/'old_inputs/data/processed/pit_attention/panel_moat_bank_v6b.csv'
    spans = align.load_spans(panel)
    args = shlex.split(sw.BASE); line = 1-float(args[args.index('--width')+1])
    scales = {}
    for arm in ('OLD','NEW'):
        states = EXP/'states'/arm/'a_share_daily_states_adopted.csv'
        values = align.ratios(states, spans)
        actual = align.resolve_line(values, line, .17771, .2)
        scales[arm] = dict(line=actual[0],share=actual[1],retained=actual[3],n=len(values))
    assert scales['NEW']['retained'], scales
    save('buy_line_validation.json',dict(registered_share=.17771,sides=scales))
    drift.CAND_STATES=EXP/'states/NEW/a_share_daily_states_adopted.csv'
    drift.HOLD_STATES=EXP/'states/NEW/a_share_daily_states_hold.csv';drift.PANEL=panel
    sys.argv=['scale']
    with (EXP/'scale_drift.txt').open('w') as out, contextlib.redirect_stdout(out):
        assert drift.main() == 0
    signals = {}
    original = edge.print_block
    for arm in ('OLD','NEW'):
        signals[arm] = {}
        def capture(title, result, note=''):
            signals[arm][title.split()[0]+title.split()[1]] = result
            return original(title,result,note)
        edge.print_block = capture
        sys.argv = ['edge','--candidate-log',str(EXP/f'candidates_{arm}.csv'),
                    '--trade-log',str(EXP/f'ledger_{arm}.csv')]
        with (EXP/f'selection_{arm}.txt').open('w') as out, contextlib.redirect_stdout(out):
            assert edge.main() == 0
        states=EXP/'states'/arm
        run_report(f'pv_forward_{arm}.txt','panel_tier_forward.py',[
            '--states',states/'a_share_daily_states_adopted.csv','--panel',panel,'--since',sw.EX5_ANCHOR_START,
            '--ohlcv-dir',EXP/'old_inputs/data/raw/ohlcv','--actions',EXP/'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'])
        for tol in (.04,.10,.15):
            run_report(f'swap_{arm}_{tol:.2f}.txt','swap_regime_control.py',[
                '--candidate-log',EXP/f'candidates_{arm}.csv','--trade-log',EXP/f'ledger_{arm}.csv',
                '--states',states/'a_share_daily_states_adopted.csv','--hold-states',states/'a_share_daily_states_hold.csv',
                '--panel',panel,'--since',sw.EX5_ANCHOR_START,'--tol',tol])
    edge.print_block = original
    paired = {}
    for label in signals['OLD']:
        values = {a: dict(zip(signals[a][label].get('days',[]),signals[a][label].get('diffs',[]))) for a in signals}
        common = sorted(values['OLD'].keys() & values['NEW'].keys())
        deltas = {d:values['NEW'][d]-values['OLD'][d] for d in common}
        years=defaultdict(list)
        for d,v in deltas.items():years[d[:4]].append(v)
        ym={y:st.median(v) for y,v in years.items()}
        paired[label] = dict(common_days=len(common),old_days=len(values['OLD']),new_days=len(values['NEW']),
            median_delta=st.median(deltas.values()) if deltas else None,positive_days=sum(v>0 for v in deltas.values()),
            yearly_medians=ym,positive_years=sum(v>0 for v in ym.values()),
            note='Paired common coverage diagnostic; overlapping days and stock/date rows are not independent samples')
    save('signal_pairs.json',paired)
    rows = read(EXP/'summary_rows.csv')
    anchors={a:next(r for r in rows if r['arm']==a and r['group']=='full' and r['start']==sw.EX5_ANCHOR_START) for a in signals}
    trade_paths={a:EXP/f"contrib_{r['tag']}_trades.csv" for a,r in anchors.items()}
    run_report('attribution.txt','delta_attribution.py',['--base',trade_paths['OLD'],'--arm',trade_paths['NEW']])
    blocks=[]
    for old in (r for r in rows if r['arm']=='OLD'):
        new=next(r for r in rows if r['arm']=='NEW' and r['group']==old['group'] and r['start']==old['start'])
        fields=('互不重叠5年块中位','逐年收益中位','逐年最差')
        blocks.append(dict(group=old['group'],start=old['start'],**{k:100*(float(new[k])-float(old[k])) for k in fields}))
    save('nonoverlap_pairs.json',blocks)
    index=read(ROOT/'data/backtest/scan_arms_index.csv')
    save('diagnostics_validation.json',dict(job_id=os.getenv('SLURM_JOB_ID'),status='passed',
        family_arms_tested=1,registered_arm_rows=len(index),signals=paired,
        no_parameter_changes=True,attribution='attribution.txt',scale='scale_drift.txt'))


if __name__ == '__main__':main()

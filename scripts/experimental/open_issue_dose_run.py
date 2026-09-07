#!/usr/bin/env python3
"""复用现行 BASE 生成本轮赢家锚点和十条在册候选的 K 剂量。"""
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from sweep_backtest_configs import BASE, DEFAULT_STARTS, METRIC_VERSION


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workers', type=int, default=56)
    args = ap.parse_args()
    exp = ROOT / 'data/experiments/exp_open_issues_20260907'
    sig = exp / 'sig/BASE'
    sig.mkdir(parents=True, exist_ok=True)
    files = {}
    for p in [ROOT / 'scripts/backtest_valuation_strategy.py',
              ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv',
              ROOT / 'data/processed/a_share_daily_states_adopted.csv',
              ROOT / 'data/processed/a_share_daily_states_hold.csv',
              ROOT / 'data/raw/corporate_actions/a_share_corporate_actions.csv',
              ROOT / 'data/reference/cost_of_equity_inputs.csv', exp / 'configs/candidates.txt']:
        h = hashlib.sha256()
        with p.open('rb') as fh:
            for block in iter(lambda: fh.read(8 * 1024 * 1024), b''):
                h.update(block)
        files[str(p.relative_to(ROOT))] = h.hexdigest()
    (exp / 'input_manifest.json').write_text(json.dumps(
        {'base': BASE, 'starts': DEFAULT_STARTS, 'metric_version': METRIC_VERSION, 'files': files}, indent=2)+'\n')
    base_args = shlex.split(BASE); base_args.remove('--no-artifacts')
    with (sig / 'run.log').open('w') as log:
        subprocess.run([sys.executable, 'scripts/backtest_valuation_strategy.py', *base_args,
                        '--since', '2011-11-01', '--out-dir', str(sig), '--label-suffix', '_OI_FOLLOW_BASE',
                        '--candidate-log', str(sig / 'candidates.csv'), '--trade-log', str(sig / 'ledger.csv')],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    trades = list(sig.glob('*_trades.csv')); assert len(trades) == 1, trades
    subprocess.run([sys.executable, 'scripts/experimental/ex_winner_dose.py', str(exp/'configs/candidates.txt'),
                    '--challenger', 'OI160_164', '--trades', str(trades[0]), '--out', str(exp/'sweep_dose.txt'),
                    '--workers', str(args.workers)], cwd=ROOT, check=True)
    for line in (exp/'configs/candidates.txt').read_text().splitlines():
        label = line.split('|')[0]
        if label == 'BASE':
            continue
        with (exp/f'report_dose_{label}.txt').open('w') as out:
            subprocess.run([sys.executable, 'scripts/experimental/ex_winner_symmetry_report.py',
                            str(exp/'sweep_dose.txt'), '--challenger', label], cwd=ROOT, stdout=out, check=True)


if __name__ == '__main__':
    main()

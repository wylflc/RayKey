#!/usr/bin/env python3
"""余仓清空研究：复用锁定 BASE 重放锚点，保留实际成交、候选与净值供诊断。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / 'data/experiments/exp_residual_clear'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--labels', default='BASE,RC150')
    args = ap.parse_args()
    manifest = json.loads((EXP / 'input_manifest.json').read_text())
    base = shlex.split(manifest['base'])
    base.remove('--no-artifacts')
    arms = dict(line.split('|', 1) for line in (EXP / 'configs/dose.txt').read_text().splitlines()
                if line and not line.startswith('#'))

    def run(label):
        out = EXP / 'sig' / label
        out.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(ROOT / 'scripts/backtest_valuation_strategy.py'), *base,
                   *shlex.split(arms[label]), '--since', '2011-11-01', '--out-dir', str(out),
                   '--label-suffix', '_RC_DIAG_' + label, '--candidate-log', str(out / 'candidates.csv'),
                   '--trade-log', str(out / 'ledger.csv')]
        with (out / 'run.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(label + ': anchor complete', flush=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(run, args.labels.split(',')))


if __name__ == '__main__':
    main()

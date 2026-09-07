#!/bin/bash
#SBATCH -J rk_rccny
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 00:20:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_residual_cny
python3 scripts/test_residual_cny.py
python3 - <<'PY'
import hashlib, json, sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, 'scripts')
from sweep_backtest_configs import BASE, DEFAULT_STARTS, METRIC_VERSION
paths = ['scripts/backtest_valuation_strategy.py', 'scripts/sweep_backtest_configs.py',
         'data/processed/a_share_daily_states_adopted.csv',
         'data/processed/a_share_daily_states_hold.csv',
         'data/processed/pit_attention/panel_moat_bank_v6b.csv',
         'data/raw/corporate_actions/a_share_corporate_actions.csv',
         'data/reference/cost_of_equity_inputs.csv',
         'data/experiments/exp_residual_cny/configs/dose.txt']
files = []
for name in paths:
    path = Path(name)
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(block)
    files.append({'path': name, 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size})
Path('data/experiments/exp_residual_cny/input_manifest.json').write_text(
    json.dumps({'created_at_utc': datetime.now(timezone.utc).isoformat(), 'base': BASE,
                'starts': DEFAULT_STARTS, 'metric_version': METRIC_VERSION, 'files': files},
               ensure_ascii=False, indent=2) + '\n')
PY
python3 scripts/sweep_backtest_configs.py "$EXP/configs/dose.txt" \
  --out "$EXP/sweep_dose.txt" --workers 56 \
  --title "卖出计划固定金额清尾：4万/5万/6万元" | tee "$EXP/report_dose.txt"
python3 - <<'PY'
import shutil, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from sweep_backtest_configs import DEFAULT_STARTS, summary_tag
from experimental.ex_winner_symmetry import top5
target = Path('data/experiments/exp_residual_cny/summaries')
target.mkdir(exist_ok=True)
base_top5 = ','.join(top5('BASE', '2011-11-01'))
for label in ['BASE', 'CNY40', 'CNY50', 'CNY60']:
    for start in DEFAULT_STARTS:
        for excluded in ['', base_top5]:
            name = f'summary_{summary_tag(label, start, excluded)}.csv'
            source = Path('data/backtest') / name
            assert source.exists(), source
            shutil.copyfile(source, target / name)
rows = Path('data/experiments/exp_residual_cny/sweep_dose.txt').read_text().splitlines()
assert not any('|ERR' in row or '|EMPTY' in row for row in rows)
assert len([row for row in rows if row and not row.startswith('#')]) == 112
print('Complete: 4 arms × 14 starts × full/A, all 112 results present.')
PY

#!/bin/bash
#SBATCH -J rk_oi165
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 00:20:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 scripts/test_build_moat_panel.py
python3 - <<'PYCODE'
import json, subprocess
from pathlib import Path
exp = Path('data/experiments/exp_oi165_panel')
commit = json.loads((exp/'entry_evidence.json').read_text())['base_commit']
(exp/'panel_before_v6b.csv').write_bytes(subprocess.check_output([
    'git', 'show', f'{commit}:data/processed/pit_attention/panel_moat_bank_v6b.csv']))
PYCODE
python3 scripts/sweep_backtest_configs.py data/experiments/exp_oi165_panel/guard_configs.txt \
  --out data/experiments/exp_oi165_panel/sweep_guard.txt --workers 56 \
  --title 'OI-165 原入池日期补接：修复前后护栏' \
  > data/experiments/exp_oi165_panel/report_guard.txt

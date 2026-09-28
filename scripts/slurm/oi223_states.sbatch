#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi223_states
#SBATCH --output=logs/oi223_states_%j.out
#SBATCH --error=logs/oi223_states_%j.err
# OI-223 折现率分档：冻结 v4.215 现存状态 → 由冻结带建时点分档表 → CONTROL／TIERS 全市场重建 → CONTROL 复现核对 → 买入线对齐容差
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi223_20260928
if [ ! -f "$E/before_manifest.json" ]; then /usr/bin/time -v python3 $E/prepare.py; fi
if [ ! -f "$E/discount_rate_tiers_pit.csv" ]; then
  /usr/bin/time -v python3 scripts/build_discount_rate_tiers.py --bands $E/old_inputs/data/processed/roic_bands.csv \
    --first-year 2002 --out $E/discount_rate_tiers_pit.csv
fi
cd $E
/usr/bin/time -v python3 build.py
/usr/bin/time -v python3 verify.py
/usr/bin/time -v python3 align_check.py

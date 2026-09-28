#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=v4219_install
#SBATCH --output=logs/v4219_install_%j.out
#SBATCH --error=logs/v4219_install_%j.err
# v4.213 落地：安装 RO 状态与原文版本登记表 → BASE 重登 → §6.7 第 4～6 步 → 决策日志 → 重发 09-28 执行清单 → 终检
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_land_v4219_20260928
export EXP_SIGNAL=2026-09-28
if [ "${STAGE:-all}" != tail ]; then
if [ "${STAGE:-all}" != from_register ]; then (cd $E && /usr/bin/time -v python3 publish.py); fi
(cd $E && python3 register.py)
SIGNAL_DATE=2026-09-28 SINCE=2026-09-24 bash scripts/slurm/refresh_pool_from_bands.sbatch
python3 scripts/check_swap_margin_scale_drift.py || echo "DRIFT_GUARD_NONZERO"
fi
python3 $E/log.py
SCAN_STAGE=scan SCAN_DATE=2026-09-28 SCAN_NAV=2625707.85 SCAN_FUNDS=-13153.46 SCAN_CASH=0 SCAN_DEBT=1812181.15 \
  bash scripts/slurm/daily_postclose.sbatch
(cd $E && python3 finish.py)

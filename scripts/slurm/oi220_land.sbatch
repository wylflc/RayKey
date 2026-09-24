#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi220_land
#SBATCH --output=logs/oi220_land_%j.out
#SBATCH --error=logs/oi220_land_%j.err
# OI-220 落地（v4.208）：安装 P 臂历史状态 → BASE 重登 → §6.7 第 4～6 步（信号日 EXP_SIGNAL，缺省 2026-09-24）→ 重发信号日执行清单 → 终检
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi220_20260925
D=${EXP_SIGNAL:-2026-09-24}
export EXP_SIGNAL=$D
# STAGE=tail 只重跑重发与终检（前段已完成时用）
if [ "${STAGE:-all}" != tail ]; then
(cd $E && /usr/bin/time -v python3 publish.py && python3 register.py)
SIGNAL_DATE=$D SINCE=${EXP_SINCE:-2026-09-23} bash scripts/slurm/refresh_pool_from_bands.sbatch
python3 scripts/check_swap_margin_scale_drift.py || echo "DRIFT_GUARD_NONZERO"
fi
(cd $E && python3 scan.py && python3 finish.py)

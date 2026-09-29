#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:50:00
#SBATCH --job-name=oi237_detail
#SBATCH --output=logs/oi237_detail_%j.out
#SBATCH --error=logs/oi237_detail_%j.err
# OI-237 补充（v4.221 状态）：7 臂 × 14 起点逐 (代码, 年) contrib（只记账补丁）→ detail/，再汇总 yearly.md；须在 oi237_run 完成后跑
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi237_20260930
test -f summary_rows.csv
WORKERS=30 /usr/bin/time -v python3 detail.py
python3 yearly.py

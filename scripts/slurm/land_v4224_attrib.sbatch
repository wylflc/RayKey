#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=land_v4224_at
#SBATCH --output=logs/land_v4224_attrib_%j.out
#SBATCH --error=logs/land_v4224_attrib_%j.err
# v4.224 读数归因：CUR 与 K1 两个长跑起点导出逐笔周期，按代码汇总贡献差（参考，不改规则）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_land_v4224_20260930
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 attrib.py

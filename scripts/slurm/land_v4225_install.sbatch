#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:30:00
#SBATCH --job-name=land_v4225_in
#SBATCH --output=logs/land_v4225_install_%j.out
#SBATCH --error=logs/land_v4225_install_%j.err
# v4.225：NEW 三侧逐日状态安装为正式状态（先验失败即停），随后写决策日志行（须早于重发扫描）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_land_v4225_20260930
python3 install.py
python3 log.py

#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=03:00:00
#SBATCH --job-name=oi204_states
#SBATCH --output=logs/oi204_states_%j.out
#SBATCH --error=logs/oi204_states_%j.err
# OI-204／211：冻结现存状态 → 四臂全市场重建 → CONTROL 复现核对 → 买入线对齐容差
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi204_211_20260924
if [ ! -f "$E/before_manifest.json" ]; then /usr/bin/time -v python3 $E/prepare.py; fi
cd $E
/usr/bin/time -v python3 build.py
/usr/bin/time -v python3 verify.py
/usr/bin/time -v python3 align_check.py

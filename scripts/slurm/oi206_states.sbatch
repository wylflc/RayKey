#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi206_states
#SBATCH --output=logs/oi206_states_%j.out
#SBATCH --error=logs/oi206_states_%j.err
# OI-206 每股增速腿：冻结 v4.213 现存状态 → CONTROL／T08／T12／T16 全市场重建 → CONTROL 复现核对 → 买入线对齐容差
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi206_20260928
if [ ! -f "$E/before_manifest.json" ]; then /usr/bin/time -v python3 $E/prepare.py; fi
cd $E
/usr/bin/time -v python3 build.py
/usr/bin/time -v python3 verify.py
/usr/bin/time -v python3 align_check.py

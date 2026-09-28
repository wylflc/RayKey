#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=v4215_states
#SBATCH --output=logs/v4215_states_%j.out
#SBATCH --error=logs/v4215_states_%j.err
# v4.215 落地（OI-207）：冻结现存状态 → CONTROL／H2 银行覆盖重跑 → CONTROL 复现核对 → 买入线对齐容差
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_land_v4215_20260928
if [ ! -f "$E/before_manifest.json" ]; then /usr/bin/time -v python3 $E/prepare.py; fi
cd $E
/usr/bin/time -v python3 build.py
/usr/bin/time -v python3 verify.py
/usr/bin/time -v python3 align_check.py

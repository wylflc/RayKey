#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi213_fair
#SBATCH --output=logs/oi213_fair_%j.out
#SBATCH --error=logs/oi213_fair_%j.err
# OI-213 机制读数（主证据）与公允性检验（参考，2018-05 起）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi213_20260928/control_validation.json
cd data/experiments/exp_oi213_20260928
FAIR_ARM=RD /usr/bin/time -v python3 fairness.py
/usr/bin/time -v python3 mechanism.py

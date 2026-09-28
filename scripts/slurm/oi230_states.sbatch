#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi230_states
#SBATCH --output=logs/oi230_states_%j.out
#SBATCH --error=logs/oi230_states_%j.err
# OI-230 候选检验（preregister.md）：冻结现存状态 → CONTROL／DC_K0／两个 RAW 臂银行覆盖重跑 → k 校准 → DC（k_DC）→
# CONTROL 复现核对 → 买入线对齐（L1）→ 估值层读数 V1、V2、V4、V5
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi230_20260929
if [ ! -f "$E/before_manifest.json" ]; then /usr/bin/time -v python3 $E/prepare.py; fi
cd $E
/usr/bin/time -v python3 build.py
/usr/bin/time -v python3 verify.py
/usr/bin/time -v python3 align_check.py
/usr/bin/time -v python3 valuation.py

#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi222_read
#SBATCH --output=logs/oi222_read_%j.out
#SBATCH --error=logs/oi222_read_%j.err
# OI-222 第一份机会／陷阱读数（§12.1 第 13 款）：BASE 14 起点带逐周期产物重跑并核对在册读数 → 生产逐日状态上的估值层与策略层读数
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
EXP=data/experiments/exp_oi222_20260925/first_reading
/usr/bin/time -v python3 $EXP/run_base.py
/usr/bin/time -v python3 scripts/experimental/opportunity_trap_audit.py \
  --states BASE=data/processed/a_share_daily_states_adopted.csv \
  --trades "BASE=$EXP/bt/*/*_trades.csv" \
  --out $EXP/report.md

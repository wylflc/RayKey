#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=longrun_now
#SBATCH --output=logs/longrun_now_%j.out
#SBATCH --error=logs/longrun_now_%j.err
# 长跑持仓延至 09-29（描述性）：实验目录内续行情 → §6.7 第 2／2b／3 步重建状态 → 对在册子集核对 → 两臂 × 14 起点长跑
# STAGES 可只跑其中几段（缺省全部）：sbatch --export=ALL,STAGES="validate run" scripts/slurm/longrun_now.sbatch
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_longrun_now_20260930
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
STAGES="${STAGES:-fetch build validate run}"
for stage in $STAGES; do
  echo "=== [$(date +%H:%M:%S)] $stage ==="
  case "$stage" in
    fetch) /usr/bin/time -v python3 fetch.py ;;
    build) /usr/bin/time -v python3 build.py ;;
    validate) /usr/bin/time -v python3 validate.py ;;
    run) WORKERS=16 /usr/bin/time -v python3 run.py ;;
  esac
done
echo "=== [$(date +%H:%M:%S)] done ==="

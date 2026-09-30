#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=land_v4224
#SBATCH --output=logs/land_v4224_%j.out
#SBATCH --error=logs/land_v4224_%j.err
# v4.224（OI-244，取消银行同尺系数）：由正式输入重建 §6.7 第 3 步两臂（K7045 复现、K1 落地），原线合格面，BASE 14 起点 CUR 对 K1
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
EXP=data/experiments/exp_land_v4224_20260930
/usr/bin/time -v python3 $EXP/build.py
python3 scripts/experimental/align_buy_line.py data/processed/a_share_daily_states_adopted.csv $EXP/states/K1/a_share_daily_states_adopted.csv \
  --base-line 1.0034 --registered-share 11.761 > $EXP/align.txt 2>&1 || true
cat $EXP/align.txt
cd $EXP && WORKERS=30 /usr/bin/time -v python3 run.py

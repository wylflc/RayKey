#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=oi228_us
#SBATCH --output=logs/oi228_us_%j.out
#SBATCH --error=logs/oi228_us_%j.err
# OI-228：按申报报表币与准则取数后重建美股历史状态。候选阶段（STAGE=candidate，缺省）写实验目录 us/states_adopted.csv 并与
# v4.218 生产状态对比；落地（STAGE=land）写 data/processed/us_daily_states_{adopted,hold}.csv
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi228_20260929
W=${WORKERS:-16}
if [ "${STAGE:-candidate}" = land ]; then
  /usr/bin/time -v python3 $E/tools/us_states.py --workers $W
  cp data/processed/us_daily_states_adopted.csv data/processed/us_daily_states_hold.csv
  ls -la data/processed/us_daily_states_*.csv; exit 0
fi
/usr/bin/time -v python3 $E/tools/us_states.py --workers $W --out $E/us/states_adopted.csv
python3 $E/tools/compare_us.py $E/us/states_adopted.csv > $E/us/compare.txt
cat $E/us/compare.txt | head -60

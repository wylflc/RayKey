#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=oi226_us
#SBATCH --output=logs/oi226_us_%j.out
#SBATCH --error=logs/oi226_us_%j.err
# OI-226：美股历史状态按现行口径重建（WACC=r 与 OI-216 标签组）→ data/processed/us_daily_states_{adopted,hold}.csv；
# 另以 09-24 代码复现、OI-216 前取数两个变体只算逐申报带作归因；OI-150 前向检验按现行口径重跑到实验目录（原记录不动）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi226_20260928
W=${WORKERS:-16}
T=${TMPDIR:-/tmp}/oi226_$SLURM_JOB_ID
mkdir -p $T $E/us $E/oi150
# STAGE=r2：第二轮台积电余项（ifrs-full IFRS 16 租赁负债、其他流动金融资产不计现金类）只重建美股状态并与第一轮对比；
# OI-150 对 ifrs-full 公司不估值（share_basis_unverified），第二轮不重跑
if [ "${STAGE:-all}" = r2 ]; then
  mkdir -p $E/us_r2
  [ -f $E/us_r2/old_states_adopted.csv ] || cp data/processed/us_daily_states_adopted.csv $E/us_r2/old_states_adopted.csv
  /usr/bin/time -v python3 $E/tools/us_states.py --variant current --bands-dir us_r2 --workers $W
  cp data/processed/us_daily_states_adopted.csv data/processed/us_daily_states_hold.csv
  python3 $E/tools/compare_us_r2.py > $E/us_r2/compare.txt
  rm -rf $T; ls -la data/processed/us_daily_states_*.csv $E/us_r2; exit 0
fi
[ -f $E/us/old_states_adopted.csv ] || cp data/processed/us_daily_states_adopted.csv $E/us/old_states_adopted.csv
/usr/bin/time -v python3 $E/tools/us_states.py --variant current --workers $W
cp data/processed/us_daily_states_adopted.csv data/processed/us_daily_states_hold.csv
python3 $E/tools/us_states.py --variant oi210 --workers $W --out $T/states_oi210.csv
python3 $E/tools/us_states.py --variant pre4214 --workers $W --out $T/states_pre4214.csv
python3 $E/tools/compare_us.py > $E/us/compare.txt
/usr/bin/time -v python3 $E/tools/oi150_rerun.py value --workers $W
python3 $E/tools/oi150_rerun.py report
python3 $E/tools/compare_oi150.py > $E/oi150/compare.txt
rm -rf $T
ls -la data/processed/us_daily_states_*.csv $E/us $E/oi150

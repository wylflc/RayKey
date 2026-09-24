#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi210_us
#SBATCH --output=logs/oi210_us_%j.out
#SBATCH --error=logs/oi210_us_%j.err
# OI-210：标普 500 历史状态按统一口径重建 → 对齐臂 → BASE_US／OLDLINE／SP100／ALIGNED 9 起点 → H1 读数；A 股 v4.201 无融资对照 14／9 起点
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi210_20260924
W16=${WORKERS:-16}   # 30 个并行路径在 32 核内存下曾被 OOM 杀掉一条（作业 27110719）
# STAGE=us_sweep 只重跑美股扫描与 H1 读数（状态与对齐臂已完成时用）
if [ "${STAGE:-all}" != us_sweep ]; then
[ -f $E/us/old_states_adopted.csv ] || cp data/processed/us_daily_states_adopted.csv $E/us/old_states_adopted.csv
/usr/bin/time -v python3 $E/us_states.py --workers 30
cp data/processed/us_daily_states_adopted.csv data/processed/us_daily_states_hold.csv
python3 scripts/experimental/align_buy_line.py data/processed/a_share_daily_states_adopted.csv data/processed/us_daily_states_adopted.csv \
  --base-line 0.9524 --swap-margin 0.15 \
  --base-panel data/processed/pit_attention/panel_moat_bank_v6b.csv --panel data/processed/pit_attention/panel_sp500_us.csv | tee $E/us/align.txt
W=$(grep -oP '`--width \K[-0-9.]+' $E/us/align.txt | tail -1 || true)
MARGIN=$(grep -oP '换仓改善 \*\*\K[0-9.]+' $E/us/align.txt | tail -1 || true)
if [ -n "$W" ] && [ -n "$MARGIN" ]; then
  grep -q '^ALIGNED|' $E/configs_us.txt || echo "ALIGNED|--width $W --swap-margin $MARGIN" >> $E/configs_us.txt
else
  echo "ALIGN_PARSE_FAILED"
fi
fi
python3 scripts/sweep_backtest_configs.py $E/configs_us.txt --out $E/scan_us.txt --market us --workers $W16 --title "OI-210 美股标普500历史成分（统一口径，现金账户）"
python3 scripts/sweep_backtest_configs.py --report --out $E/scan_us.txt --title "OI-210 美股标普500历史成分（统一口径，现金账户）" > $E/scan_us_report.txt
for ARM in BASE OLDLINE SP100 ALIGNED; do
  python3 scripts/experimental/us_h1_readout.py --scan $E/scan_us.txt --arm $ARM > $E/h1_readout_$ARM.txt || echo "H1_$ARM failed"
done
[ "${STAGE:-all}" = us_sweep ] && exit 0
python3 scripts/sweep_backtest_configs.py $E/configs_a_nocredit.txt --out $E/scan_a_nocredit.txt --workers $W16 --title "OI-210 A 股无融资对照（v4.201）"
python3 scripts/sweep_backtest_configs.py --report --out $E/scan_a_nocredit.txt --title "OI-210 A 股无融资对照（v4.201）" > $E/scan_a_nocredit_report.txt
STARTS=2012-05-01,2012-11-01,2013-05-01,2013-11-01,2014-05-01,2014-11-01,2015-05-01,2015-11-01,2016-05-01
python3 scripts/sweep_backtest_configs.py $E/configs_a_nocredit.txt --out $E/scan_a_nocredit_9.txt --workers $W16 --starts "$STARTS" --title "OI-210 A 股无融资对照（9 起点）"
python3 scripts/sweep_backtest_configs.py --report --out $E/scan_a_nocredit_9.txt --starts "$STARTS" --title "OI-210 A 股无融资对照（9 起点）" > $E/scan_a_nocredit_9_report.txt

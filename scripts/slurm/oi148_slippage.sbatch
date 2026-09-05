#!/bin/bash
#SBATCH -J rk_oi148
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 02:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-148 执行成本压力档位 0／10／20／30bp：①0bp 逐位复现（14 起点读数对 exp_metric_m2、2011 锚点产物逐字节）；
# ②BASE 与 BUY2 各档两遍（全样本＋A，A 按 0bp 锚点自动取）；③剔除集 U 按 0bp 锚点固定单遍；④成交价核对与报告。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi148_slippage
mkdir -p "$EXP/artifacts"
BASECMD=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts ',''))")
echo "=== [$(date +%T)] 2011-11-01 锚点：0bp 与 30bp 带产物与成交流水（后台）==="
for BP in 0 30; do
  # shellcheck disable=SC2086
  python3 scripts/backtest_valuation_strategy.py $BASECMD --since 2011-11-01 --slippage-bp $BP \
    --out-dir "$EXP/artifacts" --label-suffix "_slip${BP}_BASE" --artifacts \
    --trade-log "$EXP/artifacts/ledger_slip${BP}.csv" > "$EXP/artifacts/run_slip${BP}.log" 2>&1 &
done
echo "=== [$(date +%T)] 各档两遍（8 臂 × 14 起点 × 2）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/slip_tiers.txt" --out "$EXP/sweep_tiers.txt" --workers 58 \
  --title "OI-148 执行成本压力 0／10／20／30bp（BASE 与 BUY2 同档；剔除集 A 按 0bp 锚点）" | tee "$EXP/report_tiers.txt"
echo "=== [$(date +%T)] 剔除集 U（BUY2 0bp 锚点固定）单遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/slip_tiers.txt" --out "$EXP/sweep_tiers_U.txt" --workers 58 \
  --exclude-codes 000338,000651,000933,002128,601088,688516 \
  --title "OI-148 剔除集 U（BUY2，按 0bp 锚点固定）" | tee "$EXP/report_tiers_U.txt"
wait
echo "=== [$(date +%T)] 报告 ==="
python3 scripts/experimental/oi148_slippage_report.py --exp "$EXP" | tee "$EXP/report.txt"
echo "=== [$(date +%T)] 完成 ==="

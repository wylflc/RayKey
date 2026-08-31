#!/bin/bash
#SBATCH -J rk_corrarm
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.145 相关性过滤上限剂量臂（轨道 B）。两段：
#   1) 23 起点 × 4 臂 × 两遍（全样本＋去赢家，§12.1 第 2/3 款）= 184 次运行，出决策读数；
#   2) C100 臂的标准长跑带两份日志，跑信号层三表与表 3 对照组（§12.1 第 9 款要求候选臂
#      与 BASE 各一遍；BASE 侧读数已在 §12.143/§12.144 登记）。
# 单次回测实测约 1.5 分钟（rk_seledge 26254158：2011-11-01 全程 81 秒）、峰值 1.49 GB。
# --workers 24 ≈ 36 GB，低于 -n 32 的 56 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/processed/experiments/exp_corr_filter
mkdir -p "$EXP"

echo "=== [$(date +%H:%M:%S)] 第 1 段：23 起点 × 4 臂 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/corr_arms.txt" \
  --out "$EXP/sweep_corr.txt" \
  --workers 24 \
  --title "相关性过滤上限 0.60/0.70/0.85/1.00（§12.145 轨道 B）" \
  | tee "$EXP/sweep_corr_report.txt"

echo "=== [$(date +%H:%M:%S)] 第 2 段：C100 标准长跑（带候选日志与成交流水）==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts',''))")
# 同名开关以后者为准，故直接追加 --max-corr 1.0 覆盖 BASE 的 0.70。
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASE --max-corr 1.0 \
  --since 2011-11-01 \
  --label-suffix CORR100 \
  --out-dir "$EXP" \
  --candidate-log "$EXP/candidates_c100.csv" \
  --trade-log "$EXP/trades_ledger_c100.csv"

echo "=== [$(date +%H:%M:%S)] 第 3 段：C100 的信号层三表（前向 250 日）==="
python3 scripts/experimental/selection_edge_audit.py \
  --candidate-log "$EXP/candidates_c100.csv" \
  --trade-log "$EXP/trades_ledger_c100.csv" \
  --horizon 250 | tee "$EXP/selection_edge_c100_250d.txt"

echo "=== [$(date +%H:%M:%S)] 第 4 段：C100 的表 3 对照组 ==="
python3 scripts/experimental/swap_regime_control.py \
  --candidate-log "$EXP/candidates_c100.csv" \
  --trade-log "$EXP/trades_ledger_c100.csv" \
  --states data/processed/a_share_daily_states_adopted.csv \
  --hold-states data/processed/a_share_daily_states_hold.csv \
  --panel data/processed/pit_attention/panel_moat_bank_v6b.csv \
  --split 2017 | tee "$EXP/swap_regime_c100.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
ls -la "$EXP"

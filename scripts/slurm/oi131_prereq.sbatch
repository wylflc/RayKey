#!/bin/bash
#SBATCH -J rk_oi131pre
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-131 采纳前置：① 换仓边际按 0.01 一档重定；② §12.1 第 10 款 P/V 分档前向回报。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi131_exright
S=data/processed

echo "=== [$(date +%T)] 换仓边际剂量扫描（11 档）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/margin_arms.txt" \
  --out "$EXP/sweep_margin.txt" --workers 28 \
  --title "OI-131 FIXALIGN 臂换仓边际剂量（买入线 1.0138）" | tee "$EXP/report_margin.txt"

echo "=== [$(date +%T)] 信号层 P/V 分档前向回报（修正后状态）==="
python3 scripts/experimental/panel_tier_forward.py \
  --states $S/a_share_daily_states_fix.csv \
  --panel $S/pit_attention/panel_moat_bank_v6b.csv --since 2005-01-01 \
  | tee "$EXP/tier_forward_fix.txt"
echo "=== [$(date +%T)] 完成 ==="

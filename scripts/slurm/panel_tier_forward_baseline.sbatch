#!/bin/bash
#SBATCH -J rk_tierfwd
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.1 第 9 款信号层三表之一的基线：面板在册月末 P/V → 前向 3/5 年含分红再投总回报。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

OUT=data/processed/experiments/exp_selection_edge
mkdir -p "$OUT"

echo "=== [$(date +%H:%M:%S)] P/V 分档前向回报（全池，含银行）==="
python3 scripts/experimental/panel_tier_forward.py \
  --states data/processed/a_share_daily_states_adopted.csv \
  --panel data/processed/pit_attention/panel_moat_bank_v6b.csv \
  --since 2005-01-01 | tee "$OUT/panel_tier_forward.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="

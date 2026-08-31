#!/bin/bash
#SBATCH -J rk_oi114b
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-114 换仓边际 0.19（v4.113 生产值）的 §12.1 第 9~11 款读数。
# §12.151 那批测的是 0.20；v4.113 改定 0.19 后按 §12.152 的遗留项补齐。
# Δ 归因的对照臂 = 改动前的 0.1437 生产臂（exp_oi114_swap_margin 的 _OI114SRC 长跑）。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

OLD=data/processed/experiments/exp_oi114_swap_margin
EXP=data/processed/experiments/exp_oi114_adopt_m19
PANEL=data/processed/pit_attention/panel_moat_bank_v6b.csv
ST=data/processed/a_share_daily_states_adopted.csv
HST=data/processed/a_share_daily_states_hold.csv

echo "=== [$(date +%H:%M:%S)] 1/4 M19 标准长跑（BASE 现已是 0.19，显式再给一次防缺省漂移）==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts',''))")
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASE --swap-margin 0.19 \
  --since 2011-11-01 --label-suffix _M19 --out-dir "$EXP" \
  --candidate-log "$EXP/candidates_m19.csv" --trade-log "$EXP/trades_ledger_m19.csv"

echo "=== [$(date +%H:%M:%S)] 2/4 表 1-2 边际选择检验（第 9 款）==="
python3 scripts/experimental/selection_edge_audit.py \
  --candidate-log "$EXP/candidates_m19.csv" --trade-log "$EXP/trades_ledger_m19.csv" \
  --horizon 250 | tee "$EXP/selection_edge_m19_250d.txt"

echo "=== [$(date +%H:%M:%S)] 3/4 表 3 换仓方向性四表对照（第 9 款）==="
python3 scripts/experimental/swap_regime_control.py \
  --candidate-log "$EXP/candidates_m19.csv" --trade-log "$EXP/trades_ledger_m19.csv" \
  --states "$ST" --hold-states "$HST" --panel "$PANEL" --split 2017 \
  | tee "$EXP/swap_regime_m19.txt"

echo "=== [$(date +%H:%M:%S)] 4/4 Δ 归因集中度（第 10 款；净额占比 >100% 即不得作采纳依据）==="
python3 scripts/experimental/delta_attribution.py \
  --base "$(ls "$OLD"/*_OI114SRC_trades.csv)" \
  --arm  "$(ls "$EXP"/*_M19_trades.csv)" | tee "$EXP/delta_attribution_m19.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="

#!/bin/bash
#SBATCH -J rk_oi114a
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-114 换仓边际 0.1437 → 0.20 的采纳前读数（§12.1 第 9~11 款）。
# BASE 侧的候选日志/成交流水/闭合周期复用 exp_oi114_swap_margin 的 _OI114SRC 那次长跑。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

SRC=data/processed/experiments/exp_oi114_swap_margin
EXP=data/processed/experiments/exp_oi114_adopt
PANEL=data/processed/pit_attention/panel_moat_bank_v6b.csv
ST=data/processed/a_share_daily_states_adopted.csv
HST=data/processed/a_share_daily_states_hold.csv

echo "=== [$(date +%H:%M:%S)] 1/5 M20 标准长跑（带候选日志与成交流水）==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts',''))")
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASE --swap-margin 0.20 \
  --since 2011-11-01 --label-suffix _M20 --out-dir "$EXP" \
  --candidate-log "$EXP/candidates_m20.csv" --trade-log "$EXP/trades_ledger_m20.csv"

echo "=== [$(date +%H:%M:%S)] 2/5 表 1-2 边际选择检验（M20 与 BASE 各一遍，§12.1 第 9 款）==="
python3 scripts/experimental/selection_edge_audit.py \
  --candidate-log "$EXP/candidates_m20.csv" --trade-log "$EXP/trades_ledger_m20.csv" \
  --horizon 250 | tee "$EXP/selection_edge_m20_250d.txt"
python3 scripts/experimental/selection_edge_audit.py \
  --candidate-log "$SRC/candidates_base.csv" --trade-log "$SRC/trades_ledger_base.csv" \
  --horizon 250 | tee "$EXP/selection_edge_base_250d.txt"

echo "=== [$(date +%H:%M:%S)] 3/5 表 3 换仓方向性四表对照（M20 与 BASE）==="
for arm in m20 base; do
  case $arm in
    m20)  CL="$EXP/candidates_m20.csv";  TL="$EXP/trades_ledger_m20.csv" ;;
    base) CL="$SRC/candidates_base.csv"; TL="$SRC/trades_ledger_base.csv" ;;
  esac
  python3 scripts/experimental/swap_regime_control.py \
    --candidate-log "$CL" --trade-log "$TL" \
    --states "$ST" --hold-states "$HST" --panel "$PANEL" --split 2017 \
    | tee "$EXP/swap_regime_${arm}.txt"
done

echo "=== [$(date +%H:%M:%S)] 4/5 表 4 P/V 分档前向回报（面板层，与臂无关，作不变量检验）==="
python3 scripts/experimental/panel_tier_forward.py \
  --states "$ST" --panel "$PANEL" | tee "$EXP/panel_tier_forward.txt"

echo "=== [$(date +%H:%M:%S)] 5/5 Δ 归因集中度（§12.1 第 10 款；净额占比 >100% 即不得作采纳依据）==="
BASE_TRADES=$(ls "$SRC"/*_OI114SRC_trades.csv)
ARM_TRADES=$(ls "$EXP"/*_M20_trades.csv)
python3 scripts/experimental/delta_attribution.py \
  --base "$BASE_TRADES" --arm "$ARM_TRADES" | tee "$EXP/delta_attribution_m20.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="

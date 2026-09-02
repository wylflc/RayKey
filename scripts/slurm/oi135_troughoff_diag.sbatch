#!/bin/bash
#SBATCH -J rk_todiag
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.173 补：GE_TROUGHOFF 的路径层诊断（信号层看不出增益从哪来，要看成交与持仓路径）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
D=$EXP/why; mkdir -p "$D/GE_TROUGHOFF"
BASECMD=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts ',''))")
T="--daily-states $EXP/val/GE_TROUGHOFF/states_base.csv --hold-states $EXP/val/GE_TROUGHOFF/states_hold.csv --width -0.0757"
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASECMD --since 2011-11-01 $T \
  --out-dir "$D/GE_TROUGHOFF" --label-suffix _GE_TROUGHOFF --trade-log "$D/GE_TROUGHOFF/ledger.csv" \
  > "$D/GE_TROUGHOFF/run.log" 2>&1
python3 scripts/experimental/delta_attribution.py \
  --base "$(ls "$D/BASE"/*_trades.csv | head -1)" \
  --arm  "$(ls "$D/GE_TROUGHOFF"/*_trades.csv | head -1)" --top 8 | tee "$D/attribution_troughoff.txt"

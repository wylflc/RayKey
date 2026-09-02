#!/bin/bash
#SBATCH -J rk_whydiag
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.173 机理诊断：三条通过双门槛的候选各出一份成交流水与闭合周期，2011-11-01 标准长跑。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
D=$EXP/why; mkdir -p "$D"
BASECMD=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts ',''))")
G="--daily-states $EXP/val/GUARDEFF/states_base.csv --hold-states $EXP/val/GUARDEFF/states_hold.csv --width -0.0437"

run() {  # run <臂名> <额外参数...>
  local arm="$1"; shift
  mkdir -p "$D/$arm"
  # shellcheck disable=SC2086
  python3 scripts/backtest_valuation_strategy.py $BASECMD --since 2011-11-01 "$@" \
    --out-dir "$D/$arm" --label-suffix "_$arm" --trade-log "$D/$arm/ledger.csv" \
    > "$D/$arm/run.log" 2>&1
}

run BASE &
# shellcheck disable=SC2086
run GUARDEFF $G &
run C088 --max-corr 0.88 &
run G110U --gain-sell 1.10 --gain-sell-mode ungated &
run TRAIL067 --trail-ratio 0.667 &
wait

for a in GUARDEFF C088 G110U TRAIL067; do
  echo "===== $a vs BASE ====="
  python3 scripts/experimental/delta_attribution.py \
    --base "$(ls "$D/BASE"/*_trades.csv | head -1)" \
    --arm  "$(ls "$D/$a"/*_trades.csv  | head -1)" --top 8
done | tee "$D/attribution_all.txt"
echo "=== [$(date +%T)] 完成 ==="

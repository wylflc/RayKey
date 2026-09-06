#!/bin/bash
#SBATCH -J rk_oi157g
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-157（T1_GAIN 待考察）§12.1 第 4 款③ = 第 10~12 款读数：BASE 与 T1_GAIN 各一份 2011-11-01 长跑（带候选日志与
# 成交流水、出闭合周期），信号层三表（250／750 日）＋换仓四表对照（±0.04／0.10／0.15）＋ P/V 分档前向（只依赖状态，
# 两臂相同、跑一次）＋第 11 款 Δ 归因。用法：sbatch scripts/slurm/oi157_t1gain_signal.sbatch
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_t1_info
S=data/processed; P=$S/pit_attention/panel_moat_bank_v6b.csv
BASECMD=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts ',''))")
run() {  # run <臂名> <额外参数...>
  local arm="$1"; shift
  mkdir -p "$EXP/sig/$arm"
  # shellcheck disable=SC2086
  python3 scripts/backtest_valuation_strategy.py $BASECMD --since 2011-11-01 "$@" \
    --out-dir "$EXP/sig/$arm" --label-suffix "_$arm" \
    --candidate-log "$EXP/sig/$arm/candidates.csv" --trade-log "$EXP/sig/$arm/ledger.csv" \
    > "$EXP/sig/$arm/run.log" 2>&1
}
mkdir -p "$EXP/sig"
echo "=== [$(date +%T)] 两臂 2011-11-01 长跑 ＋ P/V 分档前向 ==="
run BASE &
run T1_GAIN --t1-judge gain &
python3 scripts/experimental/panel_tier_forward.py --states $S/a_share_daily_states_adopted.csv --panel $P \
  --since 2005-01-01 > "$EXP/sig/panel_tier_forward.txt" 2>&1 &
wait
echo "=== [$(date +%T)] 信号层三表与换仓四表对照 ==="
for a in BASE T1_GAIN; do
  for H in 250 750; do
    python3 scripts/experimental/selection_edge_audit.py --candidate-log "$EXP/sig/$a/candidates.csv" \
      --trade-log "$EXP/sig/$a/ledger.csv" --horizon $H > "$EXP/sig/$a/selection_edge_${H}d.txt" 2>&1 &
  done
  for TOL in 0.04 0.10 0.15; do
    python3 scripts/experimental/swap_regime_control.py --candidate-log "$EXP/sig/$a/candidates.csv" \
      --trade-log "$EXP/sig/$a/ledger.csv" --states $S/a_share_daily_states_adopted.csv \
      --hold-states $S/a_share_daily_states_hold.csv --panel $P --split 2017 --tol $TOL \
      > "$EXP/sig/$a/swap_regime_tol${TOL}.txt" 2>&1 &
  done
done
wait
echo "=== [$(date +%T)] 第 11 款 Δ 归因（T1_GAIN vs BASE）==="
python3 scripts/experimental/delta_attribution.py --base "$(ls "$EXP/sig/BASE"/*_trades.csv | head -1)" \
  --arm "$(ls "$EXP/sig/T1_GAIN"/*_trades.csv | head -1)" --top 8 | tee "$EXP/sig/attribution_T1_GAIN.txt"
echo "=== [$(date +%T)] 完成 ==="

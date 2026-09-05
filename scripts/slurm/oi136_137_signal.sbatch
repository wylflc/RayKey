#!/bin/bash
#SBATCH -J rk_o136s
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.174 表 U／V：§12.1 第 10 款信号层（边际选择／排序信息量／换仓方向性＋四表对照）与第 11 款 Δ 归因，
# BASE／C100／G110U／组合 各一份 2011-11-01 长跑（带候选日志与成交流水；不给 --no-artifacts 以出闭合周期）。
# panel_tier_forward.py 只依赖逐日状态，三条规则臂不改状态，与 BASE 逐位相同，不重跑。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi136_137
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
run BASE &
run C100 --max-corr 1.0 &
run G110U --gain-sell 1.10 --gain-sell-mode ungated &
run C100_G110U --max-corr 1.0 --gain-sell 1.10 --gain-sell-mode ungated &
wait
echo "=== [$(date +%T)] 长跑完成，信号层三表 ==="
for a in BASE C100 G110U C100_G110U; do
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
  wait
done
echo "=== [$(date +%T)] 第 11 款 Δ 归因 ==="
for a in C100 G110U C100_G110U; do
  echo "===== $a vs BASE ====="
  python3 scripts/experimental/delta_attribution.py --base "$(ls "$EXP/sig/BASE"/*_trades.csv | head -1)" \
    --arm "$(ls "$EXP/sig/$a"/*_trades.csv | head -1)" --top 8
done | tee "$EXP/attribution_sig.txt"
echo "=== [$(date +%T)] 完成 ==="

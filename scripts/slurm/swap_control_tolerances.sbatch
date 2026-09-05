#!/bin/bash
#SBATCH -J rk_swaptol
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.1 第 9 款要求匹配对照至少取 ±0.04／±0.10／±0.15 三档、只报符号稳健的读数。
# BASE 与 C100 各三档，六个进程并行；单进程约 75 秒、内存 < 1 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

SE=data/experiments/exp_selection_edge
CF=data/experiments/exp_corr_filter
COMMON=(--states data/processed/a_share_daily_states_adopted.csv
        --hold-states data/processed/a_share_daily_states_hold.csv
        --panel data/processed/pit_attention/panel_moat_bank_v6b.csv
        --split 2017)

for TOL in 0.04 0.10 0.15; do
  python3 scripts/experimental/swap_regime_control.py \
    --candidate-log "$SE/candidates.csv" --trade-log "$SE/trades_ledger.csv" \
    "${COMMON[@]}" --tol "$TOL" > "$SE/swap_regime_tol${TOL}.txt" 2>&1 &
  python3 scripts/experimental/swap_regime_control.py \
    --candidate-log "$CF/candidates_c100.csv" --trade-log "$CF/trades_ledger_c100.csv" \
    "${COMMON[@]}" --tol "$TOL" > "$CF/swap_regime_c100_tol${TOL}.txt" 2>&1 &
done
wait

echo "=== 容差敏感性：买腿超额（早期 / 后期）==="
for TOL in 0.04 0.06 0.10 0.15; do
  B="$SE/swap_regime_tol${TOL}.txt"; [ "$TOL" = "0.06" ] && B="$SE/../exp_selection_edge/swap_regime_base.txt"
  C="$CF/swap_regime_c100_tol${TOL}.txt"; [ "$TOL" = "0.06" ] && C="$CF/swap_regime_c100.txt"
  echo "--- tol ±$TOL"
  echo -n "  BASE  "; grep -h '早期\|后期' "$B" 2>/dev/null | grep '买腿' | tr '\n' ' '; echo
  echo -n "  C100  "; grep -h '早期\|后期' "$C" 2>/dev/null | grep '买腿' | tr '\n' ' '; echo
done

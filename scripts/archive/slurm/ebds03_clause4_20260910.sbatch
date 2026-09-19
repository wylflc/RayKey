#!/bin/bash
#SBATCH -J rk_ebds03c4
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-171 EBDS03 §12.1 第 4 款三项（①换仓边际重扫 ②剔除赢家 K 剂量 ③第 10~12 款信号层／归因）＋ 第 7 款滑点四档。
# 预登记 data/experiments/exp_ebds03_clause4_20260910/preregister.md。用法：sbatch --account=tes21035 scripts/slurm/ebds03_clause4_20260910.sbatch
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
EXP=data/experiments/exp_ebds03_clause4_20260910
ENGINE=data/experiments/exp_equity_bond_20260909/high_base_engine.py
EB="--equity-bond-data data/reference/equity_bond_csi300.csv --equity-bond-mode cap --equity-bond-metric spread --equity-bond-threshold 0.03"
S=data/processed; P=$S/pit_attention/panel_moat_bank_v6b.csv
BASECMD=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts ',''))")
run() {  # run <臂名> <额外参数...>：2011-11-01 长跑，带产物、候选日志与成交流水
  local arm="$1"; shift
  mkdir -p "$EXP/sig/$arm"
  # shellcheck disable=SC2086
  python3 $ENGINE $BASECMD --since 2011-11-01 "$@" --out-dir "$EXP/sig/$arm" --label-suffix "_$arm" \
    --equity-bond-log-dir "$EXP/sig/$arm" --candidate-log "$EXP/sig/$arm/candidates.csv" --trade-log "$EXP/sig/$arm/ledger.csv" \
    > "$EXP/sig/$arm/run.log" 2>&1
}
mkdir -p "$EXP/sig" "$EXP/cache"
echo "=== [$(date +%T)] ③ 两臂 2011-11-01 长跑（后台）＋ P/V 分档前向 ==="
PID_BASE=; PID_EB=
if ! ls "$EXP/sig/BASE"/*_trades.csv >/dev/null 2>&1; then run BASE & PID_BASE=$!; else echo "  BASE 长跑已有产物，跳过"; fi
# shellcheck disable=SC2086
if ! ls "$EXP/sig/EBDS03"/*_trades.csv >/dev/null 2>&1; then run EBDS03 $EB & PID_EB=$!; else echo "  EBDS03 长跑已有产物，跳过"; fi
python3 scripts/experimental/panel_tier_forward.py --states $S/a_share_daily_states_adopted.csv --panel $P \
  --since 2005-01-01 > "$EXP/sig/panel_tier_forward.txt" 2>&1 &

echo "=== [$(date +%T)] ① 换仓边际重扫：$(grep -c '|' "$EXP/configs/margin.txt") 臂 × 14 起点 × 两遍 ==="
if [ -s "$EXP/sweep_margin.txt" ] && ! grep -q 'ERR\|EMPTY' "$EXP/sweep_margin.txt" && [ "$(grep -c '^\(EX5:\)\?[A-Z]' "$EXP/sweep_margin.txt")" = 336 ]; then
  echo "  sweep_margin.txt 已完整（336 行），跳过重扫"
else
  python3 "$EXP/launch.py" --cache-dir "$EXP/cache/margin" --sweep "$EXP/configs/margin.txt" --out "$EXP/sweep_margin.txt" --workers 56 \
    --title "OI-171 EBDS03 换仓边际 0.10~0.20 一档重扫（对照 BASE 0.15）" | tee "$EXP/report_margin.txt"
fi
python3 scripts/experimental/dose_table.py "$EXP/sweep_margin.txt" --sort label | tee "$EXP/dose_margin.txt"
python3 scripts/experimental/scan_plateau.py "$EXP/sweep_margin.txt" --label 换仓边际 --current 0.15 --scale 100 | tee "$EXP/plateau_margin.txt"

echo "=== [$(date +%T)] 第 7 款 滑点 0／10／20／30bp：$(grep -c '|' "$EXP/configs/slip.txt") 臂 × 14 起点 × 两遍（A 按 0bp BASE 锚点自动取）==="
python3 "$EXP/launch.py" --cache-dir "$EXP/cache/slip" --sweep "$EXP/configs/slip.txt" --out "$EXP/sweep_tiers.txt" --workers 56 \
  --title "OI-171 EBDS03 执行成本压力 0／10／20／30bp（同档配对）" | tee "$EXP/report_tiers.txt"
{ echo "#NOTE|U = A：EBDS03 0bp 锚点前五与 BASE 相同（§12.223 winner_sets），U 单遍即 A 单遍"; cat "$EXP/sweep_tiers.txt"; } > "$EXP/sweep_tiers_U.txt"

[ -n "$PID_BASE" ] && wait "$PID_BASE"
echo "=== [$(date +%T)] ② 剔除赢家只数 K=1／3／5／10（赢家取本批 BASE 2011-11-01 长跑 contrib）==="
TRADES=$(ls "$EXP/sig/BASE"/*_trades.csv | head -1)
python3 "$EXP/launch.py" --cache-dir "$EXP/cache/dose" scripts/experimental/ex_winner_dose.py "$EXP/configs/dose.txt" \
  --challenger EBDS03 --trades "$TRADES" --out "$EXP/sweep_dose.txt" --workers 56
python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/sweep_dose.txt" --challenger EBDS03 | tee "$EXP/report_dose.txt"

wait
echo "=== [$(date +%T)] ③ 信号层三表（250／750 日）与换仓四表对照（±0.04／0.10／0.15）==="
for a in BASE EBDS03; do
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
echo "=== [$(date +%T)] 第 11 款 Δ 归因（EBDS03 vs BASE）==="
python3 scripts/experimental/delta_attribution.py --base "$(ls "$EXP/sig/BASE"/*_trades.csv | head -1)" \
  --arm "$(ls "$EXP/sig/EBDS03"/*_trades.csv | head -1)" --top 8 | tee "$EXP/sig/attribution_EBDS03.txt"
echo "=== [$(date +%T)] 第 7 款 报告 ==="
python3 scripts/experimental/oi148_slippage_report.py --exp "$EXP" --cand EBDS03 \
  --ref-scan data/experiments/exp_m3_rereg_20260910/sweep_full_A.txt | tee "$EXP/report_slippage.txt"
echo "=== [$(date +%T)] 完成；ERR/EMPTY 行数：$(cat "$EXP"/sweep_margin.txt "$EXP"/sweep_tiers.txt "$EXP"/sweep_dose.txt | grep -c 'ERR\|EMPTY' || true) ==="
echo "EBDS03 CLAUSE4 COMPLETE"

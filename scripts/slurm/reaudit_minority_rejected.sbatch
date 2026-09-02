#!/bin/bash
#SBATCH -J rk_rerej
#SBATCH -p rome
#SBATCH -n 48
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 表 C：旧纪元被否决的候选在 OI-128 纪元上重测；表 C2：两侧估值口径统一族（买入线先重解）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
S=data/processed

echo "=== [$(date +%T)] 表 C：被否决候选重测（24 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/rejected_recheck.txt" \
  --out "$EXP/sweep_rejected.txt" --workers 44 \
  --title "§12.171 表 C 旧纪元被否决候选在 OI-128 纪元上的重测" \
  | tee "$EXP/report_rejected.txt"

echo "=== [$(date +%T)] 表 C2：两侧口径统一族的买入线重解（§12.30）==="
python3 scripts/experimental/align_buy_line.py "$S/a_share_daily_states_adopted.csv" \
  "$S/a_share_daily_states_b2.csv" "$S/a_share_daily_states_hold.csv" \
  --base-line 1.0454 --swap-margin 0.18 | tee "$EXP/align_sides.txt"
mapfile -t WIDTHS < <(grep -oP '`--width \K-?[0-9.]+' "$EXP/align_sides.txt")
echo "重解买入线：B2=${WIDTHS[0]:-NA}  MAXBOTH=${WIDTHS[1]:-NA}"
[ -n "${WIDTHS[0]:-}" ] && [ -n "${WIDTHS[1]:-}" ] || { echo "买入线重解失败，跳过表 C2"; exit 0; }

cat > "$EXP/configs/side_unify.txt" <<CFG
# §12.171 表 C2：候选侧估值口径族（§12.140 B2 全量替换、§12.150 MAXBOTH），买入线各自重解到同一在册合格面。
BASE|
B2ALL|--daily-states $S/a_share_daily_states_b2.csv --hold-states $S/a_share_daily_states_b2.csv --width ${WIDTHS[0]}
B2RAW|--daily-states $S/a_share_daily_states_b2.csv --hold-states $S/a_share_daily_states_b2.csv
MAXBOTH|--daily-states $S/a_share_daily_states_hold.csv --width ${WIDTHS[1]}
MAXRAW|--daily-states $S/a_share_daily_states_hold.csv
UNIBASE|--hold-states $S/a_share_daily_states_adopted.csv
CFG
echo "=== [$(date +%T)] 表 C2：两侧口径统一族（6 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/side_unify.txt" \
  --out "$EXP/sweep_sides.txt" --workers 44 \
  --title "§12.171 表 C2 候选侧／持仓侧估值口径统一族（买入线重解）" \
  | tee "$EXP/report_sides.txt"
echo "=== [$(date +%T)] 完成 ==="

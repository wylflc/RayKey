#!/bin/bash
#SBATCH -J rk_oi138a
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-138 C11 第一阶段：四族在现行 BASE 上重跑——三个规则族带邻档（families_stage1.txt），
# 两侧口径统一族 B2ALL／MAXBOTH 先按 §12.30 对在册线与边际重解买入线再跑（MAXRAW 为未重解对照）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi138
S=data/processed
read -r BASE_LINE BASE_MARGIN < <(python3 - <<'PY'
import shlex, sys
sys.path.insert(0, "scripts")
from sweep_backtest_configs import BASE
a = shlex.split(BASE)
print(f"{1 - float(a[a.index('--width') + 1]):.4f}", a[a.index('--swap-margin') + 1])
PY
)
echo "在册买入线 $BASE_LINE／换仓边际 $BASE_MARGIN"

echo "=== [$(date +%T)] 三个规则族（15 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/families_stage1.txt" \
  --out "$EXP/sweep_families.txt" --workers 60 \
  --title "OI-138 C11 第一阶段：卖侧容差／上移锚／加仓上限三族带邻档（现行 BASE）" | tee "$EXP/report_families.txt"

echo "=== [$(date +%T)] 两侧口径统一族：买入线重解（§12.30）==="
python3 scripts/experimental/align_buy_line.py "$S/a_share_daily_states_adopted.csv" \
  "$S/a_share_daily_states_b2.csv" "$S/a_share_daily_states_hold.csv" \
  --base-line "$BASE_LINE" --swap-margin "$BASE_MARGIN" | tee "$EXP/align_sides.txt"
mapfile -t WIDTHS < <(grep -oP '`--width \K-?[0-9.]+' "$EXP/align_sides.txt")
echo "重解买入线：B2=${WIDTHS[0]:-NA}  MAXBOTH=${WIDTHS[1]:-NA}"
[ -n "${WIDTHS[0]:-}" ] && [ -n "${WIDTHS[1]:-}" ] || { echo "买入线重解失败，跳过统一族"; exit 0; }
cat > "$EXP/configs/side_unify.txt" <<CFG
# OI-138 C11 第一阶段：两侧估值口径统一族，买入线各自重解到同一在册合格面（边际 $BASE_MARGIN）。
BASE|
B2ALL|--daily-states $S/a_share_daily_states_b2.csv --hold-states $S/a_share_daily_states_b2.csv --width ${WIDTHS[0]}
MAXBOTH|--daily-states $S/a_share_daily_states_hold.csv --width ${WIDTHS[1]}
MAXRAW|--daily-states $S/a_share_daily_states_hold.csv
CFG
echo "=== [$(date +%T)] 两侧口径统一族（3 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/side_unify.txt" \
  --out "$EXP/sweep_sides.txt" --workers 60 \
  --title "OI-138 C11 第一阶段：两侧估值口径统一族（买入线重解）" | tee "$EXP/report_sides.txt"
echo "=== [$(date +%T)] 完成 ==="

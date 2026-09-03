#!/bin/bash
#SBATCH -J rk_o142l
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# v4.134 落地（OI-142 同日一档）：sweep BASE 已带 --swap-gain-once。本作业：新基准两遍 14 起点重扫（在册读数重登、剔除集 A 复核）
# ＋ 2011-11-01 单起点流水与 swap_flow_diag 读数（同日两档计数应为 0）。规则臂不改逐日状态，不重建生产链。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_swap_variants
echo "=== [$(date +%T)] 新基准两遍 14 起点重扫 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/base_only_gso.txt" \
  --out "$EXP/sweep_newbase_gso.txt" --workers 28 \
  --title "v4.134 落地后基准（同日一档）" | tee "$EXP/report_newbase_gso.txt"
echo "=== [$(date +%T)] 2011-11-01 单起点流水 ==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix _diag180_newbase \
  --trade-log "$EXP/trades_newbase_2011.csv" --candidate-log "$EXP/cands_newbase_2011.csv" > "$EXP/diag_newbase_2011.txt" 2>&1
python3 - <<'PY'
import csv, glob
EXP = "data/processed/experiments/exp_swap_variants"
codes = set()
for f in glob.glob(f"{EXP}/trades_*_2011.csv") + glob.glob("data/processed/experiments/exp_buyline_swapdir/trades_*_2011.csv"):
    for r in csv.DictReader(open(f, encoding="utf-8")):
        codes.add(r["security_code"])
for src, dst in (("data/processed/a_share_daily_states_hold.csv", f"{EXP}/states_hold_sub.csv"),
                 ("data/processed/a_share_daily_states_adopted.csv", f"{EXP}/states_cand_sub.csv")):
    with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8", newline="") as fo:
        w = csv.writer(fo); w.writerow(["security_code", "date", "valuation_ratio"])
        for r in csv.DictReader(fi):
            if r["security_code"] in codes:
                w.writerow([r["security_code"], r["date"], r["valuation_ratio"]])
print(len(codes), "codes")
PY
python3 scripts/experimental/swap_flow_diag.py "$EXP/trades_newbase_2011.csv" "$EXP/cands_newbase_2011.csv" \
  "$EXP/states_hold_sub.csv" "$EXP/states_cand_sub.csv" > "$EXP/flow_newbase_2011.txt"
echo "=== [$(date +%T)] 完成 ==="

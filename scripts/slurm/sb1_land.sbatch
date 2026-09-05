#!/bin/bash
#SBATCH -J rk_sb1l
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# v4.135 落地（用户裁定采纳 SB1 换仓接收方守卫）：sweep BASE 已带 --swap-source-block 1。
# 本作业：①新基准与 v4.134 基准两遍 14 起点（在册读数重登、剔除集 A 复核、对 v4.134 的配对差）；②2011-11-01 两臂长跑落产物；
# ③§12.1 第 11 款归因集中度；④第 4 款② 剔除赢家只数 1/3/5/10 剂量；⑤新基准单起点流水 swap_flow_diag。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_swap_variants
echo "=== [$(date +%T)] ① 新基准 vs v4.134 两遍 14 起点 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/base_sb1_land.txt" \
  --out "$EXP/sweep_newbase_sb1.txt" --workers 60 \
  --title "v4.135 落地后基准（换仓接收方守卫 K=1）对 v4.134" | tee "$EXP/report_newbase_sb1.txt"
echo "=== [$(date +%T)] ② 2011-11-01 两臂长跑（落产物）==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
mkdir -p "$EXP/bt2011"
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --artifacts --out-dir "$EXP/bt2011" --label-suffix _land181_base \
  --trade-log "$EXP/trades_newbase_sb1_2011.csv" --candidate-log "$EXP/cands_newbase_sb1_2011.csv" > "$EXP/diag_newbase_sb1_2011.txt" 2>&1 &
python3 scripts/backtest_valuation_strategy.py $BASE --swap-source-block -1 --since 2011-11-01 --artifacts --out-dir "$EXP/bt2011" --label-suffix _land181_v4134 \
  > "$EXP/diag_v4134_2011.txt" 2>&1 &
wait
B_TR=$(ls "$EXP"/bt2011/*_land181_base_trades.csv | head -1); V_TR=$(ls "$EXP"/bt2011/*_land181_v4134_trades.csv | head -1)
echo "=== [$(date +%T)] ③ 第 11 款归因集中度（base=v4.134, arm=v4.135）==="
python3 scripts/experimental/delta_attribution.py --base "$V_TR" --arm "$B_TR" > "$EXP/attr_sb1_2011.txt" 2>&1 || echo "（delta_attribution 非零退出）"
echo "=== [$(date +%T)] ④ 第 4 款② 剔除赢家只数 1/3/5/10 ==="
python3 scripts/experimental/ex_winner_dose.py "$EXP/configs/base_sb1_land.txt" --trades "$B_TR" \
  --out "$EXP/sweep_sb1_dose.txt" --workers 60 2>&1 | tail -5
python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/sweep_sb1_dose.txt" --challenger V4134 > "$EXP/report_sb1_dose.txt" 2>&1 || echo "（symmetry_report 非零退出）"
echo "=== [$(date +%T)] ⑤ 新基准单起点流水诊断 ==="
python3 - <<'PY'
import csv, glob
EXP = "data/experiments/exp_swap_variants"
codes = set()
for f in glob.glob(f"{EXP}/trades_*_2011.csv") + glob.glob("data/experiments/exp_buyline_swapdir/trades_*_2011.csv"):
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
python3 scripts/experimental/swap_flow_diag.py "$EXP/trades_newbase_sb1_2011.csv" "$EXP/cands_newbase_sb1_2011.csv" \
  "$EXP/states_hold_sub.csv" "$EXP/states_cand_sub.csv" > "$EXP/flow_newbase_sb1_2011.txt"
echo "=== [$(date +%T)] 完成 ==="

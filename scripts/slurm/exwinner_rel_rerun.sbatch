#!/bin/bash
#SBATCH -J rk_exwrel
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 去赢家赢家尺改为「盈亏 ÷ 前一日净资产」累计贡献后的重跑：
# ① v4.135 基准（BASE）与 V4134 两遍 14 起点（第二遍按新尺剔除集 A）；② 2011-11-01 两臂长跑落产物（trades 带 contrib 列）；
# ③ 第 11 款归因（贡献尺）；④ 第 4 款② 剔除赢家只数 1/3/5/10；⑤ 剔除集 A/B/U 对称性。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_swap_variants
CFG=$EXP/configs/base_sb1_land.txt
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
mkdir -p "$EXP/bt2011_rel"
echo "=== [$(date +%T)] ①② 两遍 14 起点 ＋ 2011-11-01 两臂长跑（并行）==="
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --artifacts --out-dir "$EXP/bt2011_rel" --label-suffix _rel_base \
  > "$EXP/bt2011_rel/diag_rel_base_2011.txt" 2>&1 &
python3 scripts/backtest_valuation_strategy.py $BASE --swap-source-block -1 --since 2011-11-01 --artifacts --out-dir "$EXP/bt2011_rel" --label-suffix _rel_v4134 \
  > "$EXP/bt2011_rel/diag_rel_v4134_2011.txt" 2>&1 &
python3 scripts/sweep_backtest_configs.py "$CFG" --out "$EXP/sweep_newbase_sb1_rel.txt" --workers 60 \
  --title "去赢家赢家尺改为相对贡献：v4.135 基准对 v4.134" | tee "$EXP/report_newbase_sb1_rel.txt"
wait
B_TR=$(ls "$EXP"/bt2011_rel/*_rel_base_trades.csv | head -1); V_TR=$(ls "$EXP"/bt2011_rel/*_rel_v4134_trades.csv | head -1)
echo "=== [$(date +%T)] ③ 第 11 款归因（base=v4.134, arm=v4.135，贡献尺）==="
python3 scripts/experimental/delta_attribution.py --base "$V_TR" --arm "$B_TR" > "$EXP/attr_sb1_rel_2011.txt" 2>&1 || echo "（delta_attribution 非零退出）"
echo "=== [$(date +%T)] ④ 第 4 款② 剔除赢家只数 1/3/5/10 ==="
python3 scripts/experimental/ex_winner_dose.py "$CFG" --trades "$B_TR" --out "$EXP/sweep_sb1_dose_rel.txt" --workers 60 2>&1 | tail -6
python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/sweep_sb1_dose_rel.txt" --challenger V4134 > "$EXP/report_sb1_dose_rel.txt" 2>&1 || echo "（dose report 非零退出）"
echo "=== [$(date +%T)] ⑤ 剔除集 A/B/U 对称性（challenger V4134）==="
python3 scripts/experimental/ex_winner_symmetry.py "$CFG" --challenger V4134 --out "$EXP/sweep_sb1_sym_rel.txt" --workers 60 2>&1 | tail -8
python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/sweep_sb1_sym_rel.txt" --challenger V4134 > "$EXP/report_sb1_sym_rel.txt" 2>&1 || echo "（sym report 非零退出）"
echo "=== [$(date +%T)] 完成 ==="

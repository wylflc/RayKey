#!/bin/bash
#SBATCH -J rk_swvar
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.179：换仓机制变体（接收方守卫／触发期／卖出款分摊／三条合一／OI-142／边际粗扫，35 臂），14 起点两遍（全样本＋去赢家）。
# 末尾另跑 2011-11-01 单起点三臂的成交流水，供 swap_flow_diag.py 对照 §12.178 的 BASE／SPT015 读数。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_swap_variants
echo "=== [$(date +%T)] swapvar（$(grep -c '|' "$EXP/configs/swapvar.txt") 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/swapvar.txt" \
  --out "$EXP/sweep_swapvar.txt" --workers 60 \
  --title "§12.179 换仓机制变体" | tee "$EXP/report_swapvar.txt"
echo "=== [$(date +%T)] 单起点流水诊断（2011-11-01）==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix _diag179_spttw20 \
  --swap-proceeds target --swap-trigger-window 20 \
  --trade-log "$EXP/trades_spttw20_2011.csv" --candidate-log "$EXP/cands_spttw20_2011.csv" > "$EXP/diag_spttw20_2011.txt" 2>&1 &
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix _diag179_spl \
  --swap-proceeds split \
  --trade-log "$EXP/trades_spl_2011.csv" --candidate-log "$EXP/cands_spl_2011.csv" > "$EXP/diag_spl_2011.txt" 2>&1 &
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix _diag179_spttw20sb1 \
  --swap-proceeds target --swap-trigger-window 20 --swap-source-block 1 \
  --trade-log "$EXP/trades_spttw20sb1_2011.csv" --candidate-log "$EXP/cands_spttw20sb1_2011.csv" > "$EXP/diag_spttw20sb1_2011.txt" 2>&1 &
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix _diag179_sb1 \
  --swap-source-block 1 \
  --trade-log "$EXP/trades_sb1_2011.csv" --candidate-log "$EXP/cands_sb1_2011.csv" > "$EXP/diag_sb1_2011.txt" 2>&1 &
wait
echo "=== [$(date +%T)] 完成 ==="
echo "=== [$(date +%T)] 两侧逐日状态按流水涉及代码抽子集，出 swap_flow_diag 读数 ==="
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
for a in spttw20 spl spttw20sb1 sb1; do
  python3 scripts/experimental/swap_flow_diag.py "$EXP/trades_${a}_2011.csv" "$EXP/cands_${a}_2011.csv" \
    "$EXP/states_hold_sub.csv" "$EXP/states_cand_sub.csv" > "$EXP/flow_${a}_2011.txt"
done
for a in base spt; do
  python3 scripts/experimental/swap_flow_diag.py "data/experiments/exp_buyline_swapdir/trades_${a}_2011.csv" \
    "data/experiments/exp_buyline_swapdir/cands_${a}_2011.csv" \
    "$EXP/states_hold_sub.csv" "$EXP/states_cand_sub.csv" > "$EXP/flow_${a}_2011.txt"
done
echo "=== [$(date +%T)] 全部完成 ==="

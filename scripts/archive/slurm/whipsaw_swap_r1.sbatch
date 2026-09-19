#!/bin/bash
#SBATCH -J rk_whipsaw1
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 换仓卖出源弱势的形态复核·第一轮（data/experiments/exp_whipsaw_swap/configs/round1.txt）：
# ① 15 臂 × 14 起点 × 两遍（全样本＋去赢家 A）；② BASE 2011-11-01 summary 与 §12.193 0bp 在册产物逐位核对；
# ③ 2011-11-01 单起点逐臂成交流水＋被挡事件记录＋周期产物，供 whipsaw_swap_diag.py 复盘。
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
EXP=data/experiments/exp_whipsaw_swap
CFG="$EXP/configs/round1.txt"
echo "=== [$(date +%T)] 扫描 $(grep -c '|' "$CFG") 臂 × 14 起点 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$CFG" --out "$EXP/sweep_r1.txt" --workers 60 \
  --title "换仓弱势形态复核·第一轮" | tee "$EXP/report_r1.txt"

echo "=== [$(date +%T)] 单起点 2011-11-01 逐臂流水与被挡事件 ==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
mkdir -p "$EXP/bt2011"
grep -v '^#' "$CFG" | grep '|' | while IFS='|' read -r arm extra; do
  mkdir -p "$EXP/bt2011/$arm"
  python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix "_wh1_$arm" \
    --artifacts --out-dir "$EXP/bt2011/$arm" $extra \
    --trade-log "$EXP/bt2011/$arm/ledger.csv" --weak-block-log "$EXP/bt2011/$arm/blocked.csv" \
    > "$EXP/bt2011/$arm/run.log" 2>&1 &
done
wait
echo "=== [$(date +%T)] BASE 逐位核对（对 §12.193 0bp 在册 2011 起点 summary）==="
python3 - <<'PY'
import csv, glob
ref = [r for r in csv.DictReader(open("data/experiments/exp_oi148_slippage/artifacts/summary_slip0_BASE.csv", encoding="utf-8")) if r["策略"].startswith("trend_")][-1]
new_path = glob.glob("data/experiments/exp_whipsaw_swap/bt2011/BASE/summary_*.csv")[0]
new = [r for r in csv.DictReader(open(new_path, encoding="utf-8")) if r["策略"].startswith("trend_")][-1]
diff = [k for k in ref if k not in ("策略",) and ref[k] != new.get(k)]
print("列数", len(ref), len(new), "｜不同列：", diff if diff else "无（逐位相同）")
for k in diff[:10]:
    print(" ", k, ref[k], "→", new.get(k))
PY
echo "=== [$(date +%T)] 完成 ==="

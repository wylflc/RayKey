#!/bin/bash
#SBATCH -J rk_whipsawd
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 换仓卖出源弱势形态复核：单起点逐臂成交流水＋被挡事件记录＋周期产物，供 whipsaw_swap_diag.py 复盘。
# 用法：sbatch --export=ALL,CFG=<配置文件>,SINCE=2011-11-01 scripts/slurm/whipsaw_swap_diag.sbatch
# 产物落 data/experiments/exp_whipsaw_swap/bt<起点年份>/<臂>/；末尾把 BASE 的 summary 与 §12.193 0bp 在册产物逐位核对。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_whipsaw_swap
CFG="${CFG:-$EXP/configs/round1.txt}"
SINCE="${SINCE:-2011-11-01}"
OUT="$EXP/bt${SINCE:0:4}"
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
echo "=== [$(date +%T)] 单起点 $SINCE 逐臂流水（$CFG）==="
n=0
while IFS='|' read -r arm extra; do
  [ -z "$arm" ] && continue
  mkdir -p "$OUT/$arm"
  python3 scripts/backtest_valuation_strategy.py $BASE --since "$SINCE" --label-suffix "_wh_$arm" \
    --artifacts --out-dir "$OUT/$arm" $extra \
    --trade-log "$OUT/$arm/ledger.csv" --weak-block-log "$OUT/$arm/blocked.csv" \
    > "$OUT/$arm/run.log" 2>&1 &
  n=$((n+1))
done < <(grep -v '^#' "$CFG" | grep '|')
echo "已启动 $n 个回测进程"
wait
echo "=== [$(date +%T)] 全部结束；BASE 逐位核对（对 §12.193 0bp 在册 $SINCE 起点 summary）==="
python3 - "$OUT" "$SINCE" <<'PY'
import csv, glob, sys
out, since = sys.argv[1], sys.argv[2]
if since != "2011-11-01":
    print("非 2011-11-01 起点，无在册产物可对，跳过"); sys.exit(0)
ref = [r for r in csv.DictReader(open("data/experiments/exp_oi148_slippage/artifacts/summary_slip0_BASE.csv", encoding="utf-8")) if r["策略"].startswith("trend_")][-1]
paths = glob.glob(f"{out}/BASE/summary_*.csv")
if not paths:
    print("BASE summary 缺失"); sys.exit(1)
new = [r for r in csv.DictReader(open(paths[0], encoding="utf-8")) if r["策略"].startswith("trend_")][-1]
diff = [k for k in ref if k != "策略" and ref[k] != new.get(k)]
print("列数", len(ref), len(new), "｜不同列：", diff if diff else "无（逐位相同）")
for k in diff[:10]:
    print(" ", k, ref[k], "→", new.get(k))
PY
echo "=== [$(date +%T)] 完成 ==="

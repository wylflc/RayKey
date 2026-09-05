#!/bin/bash
#SBATCH -J rk_wstep
#SBATCH -p rome
#SBATCH -n 48
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 窗口步长与起点集的敏感度实验（用户 2026-09-01 提问）。只落逐日净值，不改任何规则：
#   BASE 与 TW000 各跑 23 个标准起点、**带产物**（需要 *_equity.csv 才能重算不同步长的窗口），
#   之后由 window_step_lab.py 在同一批净值曲线上重算：滚 5 年 × 步长 1/3/6/12 个月、滚 10 年、
#   互不重叠 5 年块，比较各口径下的 Δ(TW000 − BASE) 是否改变结论。
# 46 次运行 × 约 1.5 分钟；--workers 24 ≈ 36 GB < -n 48 的 84 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/experiments/exp_window_step
ST=data/experiments/states/exp_oi115_trailleg
mkdir -p "$EXP"

BASEARGS=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts',''))")
STARTS=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(' '.join(s.DEFAULT_STARTS))")

run_arm () {   # $1=标签  $2=额外参数
  local tag="$1"; shift
  for s in $STARTS; do
    echo "python3 scripts/backtest_valuation_strategy.py $BASEARGS $* --since $s --label-suffix ${tag}${s//-/} --out-dir $EXP/$tag"
  done
}
mkdir -p "$EXP/BASE" "$EXP/TW000"
{ run_arm BASE; run_arm TW000 --daily-states "$ST/states_TW000_cand.csv" --hold-states "$ST/states_TW000_hold.csv" --width 0.0024; } \
  > "$EXP/cmds.txt"
echo "=== [$(date +%H:%M:%S)] $(wc -l < "$EXP/cmds.txt") 次运行 ==="
xargs -P 24 -I{} -a "$EXP/cmds.txt" bash -c '{} > /dev/null 2>&1 || echo "FAIL: {}"'

echo "=== [$(date +%H:%M:%S)] 重算各口径 ==="
python3 scripts/experimental/window_step_lab.py --exp "$EXP" | tee "$EXP/window_step.txt"
echo "=== [$(date +%H:%M:%S)] 完成 ==="

#!/bin/bash
#SBATCH -J rk_oi122bp
#SBATCH -p rome
#SBATCH -n 48
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-122 比较基准的前沿预测力检验（用户 2026-09-01 指令）。只落逐日净值，不改任何规则：
#   §12.155 剂量臂 TW025/TW050/TW075/TW125 各补跑 23 个标准起点、带产物（BASE 与 TW000 曲线
#   已在 exp_window_step，臂参数照抄 exp_oi115_trailleg/configs/trail_arms.txt），
#   之后 benchmark_predictive_lab.py 在 6 臂 × 23 起点的同一批净值上做三腿检验：
#   水平腿 E(≤T)→F5(T)、Δ 腿 ΔE(≤T)→ΔF5(T)、家族排序腿（臂间比较基准的直接检验）。
# 92 次运行 × 约 1.5 分钟；--workers 24 ≈ 36 GB < -n 48 的 84 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/experiments/exp_window_step
CFG=data/experiments/exp_oi115_trailleg/configs/trail_arms.txt

BASEARGS=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts',''))")
STARTS=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(' '.join(s.DEFAULT_STARTS))")

: > "$EXP/cmds_oi122.txt"
while IFS='|' read -r tag extra; do
  case "$tag" in
    TW025|TW050|TW075|TW125)
      mkdir -p "$EXP/$tag"
      for s in $STARTS; do
        echo "python3 scripts/backtest_valuation_strategy.py $BASEARGS $extra --since $s --label-suffix ${tag}${s//-/} --out-dir $EXP/$tag"
      done >> "$EXP/cmds_oi122.txt"
      ;;
  esac
done < "$CFG"
echo "=== [$(date +%H:%M:%S)] $(wc -l < "$EXP/cmds_oi122.txt") 次运行 ==="
xargs -P 24 -I{} -a "$EXP/cmds_oi122.txt" bash -c '{} > /dev/null 2>&1 || echo "FAIL: {}"'

echo "=== [$(date +%H:%M:%S)] 三腿检验（6 臂）==="
python3 scripts/experimental/benchmark_predictive_lab.py --exp "$EXP" | tee "$EXP/benchmark_predictive.txt"
echo "=== [$(date +%H:%M:%S)] 完成 ==="

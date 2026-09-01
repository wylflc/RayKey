#!/bin/bash
#SBATCH -J rk_oi115tl
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.155 ① 利润增速腿剂量臂（轨道 B）。四段：
#   1) 建链：6 臂（W=1.0 先验 + 0/0.25/0.5/0.75/1.25）× 两侧建带 + 银行覆盖 + 合成持仓侧，
#      W=1.0 那一臂须与生产文件的 v6b 子集逐位相同（不同即停），再按 align_buy_line 同一合格面重解买入线并写配置；
#   2) 换仓边际标度诊断：逐臂报 check_swap_margin_scale_drift.py 的 `g`（边际固定 0.19 的代价）；
#   3) 7 臂 × 23 起点 × 两遍（全样本＋去赢家）= 322 次运行，出四项决策读数；
#   4) 平台最好的一臂另跑标准长跑带日志，供 §12.1 第 9~10 款的信号层三表与 Δ 归因（读数回填时再跑，本轮只留位）。
# 单臂单侧建带实测 38 s / 0.31 GB；单次回测约 1.5 分钟 / 1.49 GB。--workers 48 ≈ 72 GB < -n 64 的 112 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/processed/experiments/exp_oi115_trailleg
ST=data/processed/experiments/states/exp_oi115_trailleg
mkdir -p "$EXP" "$ST"

echo "=== [$(date +%H:%M:%S)] 1/4 建链 + 线对齐 ==="
python3 scripts/experimental/build_trailleg_arm_states.py \
  --weights 0.00,0.25,0.50,0.75,1.25 --jobs 12 | tee "$EXP/build_align.txt"

echo "=== [$(date +%H:%M:%S)] 2/4 换仓边际标度诊断（边际固定 0.19 的代价）==="
for T in TW000 TW025 TW050 TW075 TW100 TW125; do
  echo "--- $T"
  python3 scripts/check_swap_margin_scale_drift.py \
    --cand-states "$ST/states_${T}_cand.csv" --hold-states "$ST/states_${T}_hold.csv" || true
done | tee "$EXP/margin_scale_drift.txt"

echo "=== [$(date +%H:%M:%S)] 3/4 7 臂 × 23 起点 × 两遍 = 322 次运行 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/trail_arms.txt" \
  --out "$EXP/sweep_trailleg.txt" \
  --workers 48 \
  --title "① 利润增速腿权重 0/0.25/0.5/0.75/1.0/1.25（§12.155 轨道 B）" \
  | tee "$EXP/sweep_trailleg_report.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
ls -la "$EXP"

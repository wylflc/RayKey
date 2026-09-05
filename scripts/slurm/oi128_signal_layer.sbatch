#!/bin/bash
#SBATCH -J rk_oi128sig
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-128 第三轮（§12.1 第 10 款信号层）：P/V 分档前向回报，两臂各一遍。
# 这一表直接问「新口径的 P/V 排序对未来回报的判别力是变强还是变弱」——
# 与回测的收益读数相互独立，不受买入线、换仓边际、赢家集中度影响。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi128_minority
S=data/processed
P=$S/pit_attention/panel_moat_bank_v6b.csv

for arm in adopted mi; do
  echo "=== [$(date +%T)] panel_tier_forward：$arm ==="
  python3 scripts/experimental/panel_tier_forward.py \
    --states $S/a_share_daily_states_$arm.csv --panel $P --since 2005-01-01 \
    --exclude-banks --per-code-out "$EXP/tier_forward_percode_$arm.csv" \
    | tee "$EXP/tier_forward_$arm.txt"
done
echo "=== [$(date +%T)] 完成 ==="

#!/bin/bash
#SBATCH -J rk_seledge
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.1 第 9 款信号层三表的基线一次：BASE 标准长跑（2011-11-01）带 --candidate-log 与
# --trade-log，随后跑 selection_edge_audit.py。BASE 原带 --no-artifacts，此处去掉，
# 以便同时产出 *_trades.csv 供 delta_attribution.py（第 10 款）作对照臂基准。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

OUT=data/experiments/exp_selection_edge
mkdir -p "$OUT"

BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts',''))")

echo "=== [$(date +%H:%M:%S)] BASE 标准长跑（带候选日志与成交流水）==="
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASE \
  --since 2011-11-01 \
  --label-suffix SELEDGE \
  --out-dir "$OUT" \
  --candidate-log "$OUT/candidates.csv" \
  --trade-log "$OUT/trades_ledger.csv"

echo "=== [$(date +%H:%M:%S)] 信号层三表（前向 250 交易日）==="
python3 scripts/experimental/selection_edge_audit.py \
  --candidate-log "$OUT/candidates.csv" \
  --trade-log "$OUT/trades_ledger.csv" \
  --horizon 250 | tee "$OUT/selection_edge_250d.txt"

echo "=== [$(date +%H:%M:%S)] 同表换 750 交易日窗口（约 3 年）==="
python3 scripts/experimental/selection_edge_audit.py \
  --candidate-log "$OUT/candidates.csv" \
  --trade-log "$OUT/trades_ledger.csv" \
  --horizon 750 | tee "$OUT/selection_edge_750d.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
ls -la "$OUT"

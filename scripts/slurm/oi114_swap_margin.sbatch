#!/bin/bash
#SBATCH -J rk_oi114
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-114 换仓边际的标度与剂量：绝对差（现行 0.1437）vs 相对差（候选/持仓 ≤ 1−m）。
# 第 1 段先验 `--swap-margin-mode abs` 重构与改动前逐位相同（对台账里旧代码的 BASE 行），
# 不一致即退出，不烧后面 598 次运行。
# 第 2 段 13 臂 × 23 起点 × 两遍 = 598 次运行；--workers 48 ≈ 72 GB 上界，低于 -n 64 的 112 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/experiments/exp_oi114_swap_margin

echo "=== [$(date +%H:%M:%S)] 第 1 段：abs 逐位复现 ＋ ratio 确实生效 ==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
rm -f data/backtest/summary_OI114ABS.csv data/backtest/summary_OI114REL.csv
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASE --swap-margin-mode abs \
  --since 2011-11-01 --label-suffix _OI114ABS
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASE --swap-margin-mode ratio \
  --since 2011-11-01 --label-suffix _OI114REL

python3 - <<'PY_EOF'
import csv, sys

def read(path):
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["策略"].startswith("trend_")]
    return rows[-1]

led = [r for r in csv.DictReader(open("data/archive/scan_summaries_m1.csv", encoding="utf-8"))
       if r.get("扫描标签") == "BASE20111101"][-1]
abs_ = read("data/backtest/summary_OI114ABS.csv")
rel = read("data/backtest/summary_OI114REL.csv")

skip = {"策略", "扫描标签"}
keys = [k for k in abs_ if k not in skip and (abs_[k] or led.get(k))]
bad = [(k, led.get(k), abs_[k]) for k in keys if (led.get(k) or "") != (abs_[k] or "")]
print(f"① abs vs 台账旧代码 BASE：比对 {len(keys)} 个字段")
for k, a, b in bad:
    print(f"   差异 {k}: 台账 {a!r} → 新 {b!r}")
if bad:
    sys.exit("abs 模式未逐位复现，终止")
print("   逐位相同，重构未改 abs 行为")

diff = [k for k in keys if (abs_.get(k) or "") != (rel.get(k) or "")]
print(f"② ratio 同边际 0.1437：{len(diff)} 个字段与 abs 不同")
if not diff:
    sys.exit("ratio 模式与 abs 完全相同，开关未生效，终止")
for k in ("年化", "滚动5年年化中位", "年均换手", "最大回撤"):
    print(f"   {k}: abs {abs_.get(k)} → ratio {rel.get(k)}")
PY_EOF

echo "=== [$(date +%H:%M:%S)] 第 2 段：13 臂 × 23 起点 × 两遍 = 598 次运行 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/margin_arms.txt" \
  --out "$EXP/sweep_margin.txt" \
  --workers 48 \
  --title "换仓边际：绝对差 0~0.35 vs 相对差 5%~35%（OI-114）" \
  | tee "$EXP/sweep_margin_report.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="

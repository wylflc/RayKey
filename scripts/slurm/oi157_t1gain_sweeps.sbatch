#!/bin/bash
#SBATCH -J rk_oi157s
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-157（T1_GAIN 待考察）§12.1 第 4 款①②，与 OI-158 台账修复的对称性重跑。用法：
#   sbatch scripts/slurm/oi157_t1gain_sweeps.sbatch
# ① 换仓边际 0.10~0.20 一档重扫（configs/t1gain_margin.txt，12 臂 × 14 起点两遍）；
# ② 剔除赢家只数 K=1/3/5/10（configs/t1gain_dose.txt，赢家取 §12.192 m2 BASE 2011-11-01 长跑 trades 的 contrib 列）；
# ③ 剔除集 A/B/U 对称性按新标签（集合名@挑战臂）重跑 SC 与 T1_GAIN，读数须与 §12.200 提交版逐位相同。
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
EXP=data/experiments/exp_t1_info
TRADES=data/experiments/exp_metric_m2/artifacts/trend_x5_w-0.0454_x1c_dtax_sma20_swap_corr1_tranche_slmin_gs1.1u_ma60stop_addma_swk20_cap0.6_sp_gso_lot100_lrc2_m2_BASE_trades.csv

echo "=== [$(date +%T)] ① 换仓边际重扫：$(grep -c '|' "$EXP/configs/t1gain_margin.txt") 臂 × 14 起点 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/t1gain_margin.txt" --out "$EXP/sweep_t1gain_margin.txt" --workers 56 \
  --title "OI-157 T1_GAIN 换仓边际 0.01 一档重扫" | tee "$EXP/report_t1gain_margin.txt"
echo "ERR/EMPTY 行数：$(grep -c 'ERR\|EMPTY' "$EXP/sweep_t1gain_margin.txt" || true)"

echo "=== [$(date +%T)] ② 剔除赢家只数 K=1/3/5/10 ==="
python3 scripts/experimental/ex_winner_dose.py "$EXP/configs/t1gain_dose.txt" --challenger T1_GAIN --trades "$TRADES" \
  --out "$EXP/sweep_t1gain_dose.txt" --workers 56
python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/sweep_t1gain_dose.txt" --challenger T1_GAIN | tee "$EXP/report_t1gain_dose.txt"

echo "=== [$(date +%T)] ③ 对称性重跑（新标签），与提交版逐位核对 ==="
for ARM in SC T1_GAIN; do
  git show HEAD:"$EXP/exwinner_u_${ARM}.txt" > "$EXP/.exwinner_u_${ARM}_prev.txt"
  python3 scripts/experimental/ex_winner_symmetry.py "$EXP/configs/t1_u.txt" --challenger "$ARM" \
    --out "$EXP/exwinner_u_${ARM}.txt" --workers 56
  python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/exwinner_u_${ARM}.txt" --challenger "$ARM" | tee "$EXP/exwinner_u_${ARM}_report.txt"
  python3 - "$EXP/.exwinner_u_${ARM}_prev.txt" "$EXP/exwinner_u_${ARM}.txt" "$ARM" <<'PY'
import sys, re
prev, new, arm = sys.argv[1:4]
def rows(path, strip):
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("#SET|"):
            continue
        label, rest = line.rstrip("\n").split("|", 1)
        out[label.replace(strip, "", 1)] = rest
    return out
a, b = rows(prev, ""), rows(new, f"@{arm}")
same = sum(1 for k in a if b.get(k) == a[k])
print(f"{arm}: 提交版 {len(a)} 行，新标签 {len(b)} 行，逐位相同 {same} 行" + ("" if same == len(a) == len(b) else "  <<< 不一致"))
PY
  rm -f "$EXP/.exwinner_u_${ARM}_prev.txt"
done
echo "=== [$(date +%T)] 完成 ==="

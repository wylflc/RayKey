#!/bin/bash
#SBATCH -J rk_reattr
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 表 K：GUARDEFF 的 Δ 归因集中度（§12.1 第 11 款）。2011-11-01 标准长跑。
# delta_attribution.py 读的是**闭合周期**文件（`<out-dir>/<label>_trades.csv`，含 exit_date/proceeds/invested），
# 不是 `--trade-log` 的逐笔流水；故此处不给 `--no-artifacts`，并把产物落到各臂独立 out-dir。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
rm -rf "$EXP/attrib"; mkdir -p "$EXP/attrib/base" "$EXP/attrib/ge"

BASECMD=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE.replace('--no-artifacts ',''))")
G="--daily-states $EXP/val/GUARDEFF/states_base.csv --hold-states $EXP/val/GUARDEFF/states_hold.csv --width -0.0437"

# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASECMD --since 2011-11-01 \
  --out-dir "$EXP/attrib/base" --label-suffix _attrBASE > "$EXP/attrib/base.log" 2>&1 &
P1=$!
# shellcheck disable=SC2086
python3 scripts/backtest_valuation_strategy.py $BASECMD --since 2011-11-01 $G \
  --out-dir "$EXP/attrib/ge" --label-suffix _attrGE > "$EXP/attrib/ge.log" 2>&1 &
P2=$!
wait $P1 $P2

B=$(ls "$EXP/attrib/base"/*_trades.csv | head -1)
A=$(ls "$EXP/attrib/ge"/*_trades.csv | head -1)
echo "对照周期文件 $B"; echo "候选周期文件 $A"
python3 scripts/experimental/delta_attribution.py --base "$B" --arm "$A" \
  | tee "$EXP/attrib/delta_attribution.txt"

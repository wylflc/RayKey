#!/bin/bash
#SBATCH -J rk_slval
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 备用策略清单里一条「需重建」臂的建带链（docs/Ashare_strategy_shortlist.md）。用法：
#   sbatch --job-name=rk_slval_<臂> scripts/slurm/strategy_shortlist_val_arm.sbatch <臂> "<建带追加开关|->" [divspread|-] [宇宙面板|-]
# 三种形态：①追加开关非 "-"：跑 §6.7 第 2／2b／3 步；②开关 "-" 且 divspread 非 "-"：只跑第 3 步（读生产 raw 逐日）；
#           ③两者都 "-" 且面板非 "-"：只对换宇宙重解买入线。产物落 $EXP/val/<臂>/，末尾按 §12.30 重解买入线。
# 建带公共开关**不在本脚本抄写**：从 docs/000_Ashare_workflow.md §6.7 第 2 步命令现读，生产口径改了这里自动跟。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
ARM="$1"; EXTRA="${2:--}"; DIVS_ARG="${3:--}"; PANEL="${4:--}"; DIVS="$DIVS_ARG"
EXP="${EXP:-data/processed/experiments/exp_strategy_shortlist}"
S=data/processed
E="$EXP/val/$ARM"
mkdir -p "$E"

read -r BASE_LINE BASE_MARGIN < <(python3 - <<'PY'
import shlex, sys
sys.path.insert(0, "scripts")
from sweep_backtest_configs import BASE
a = shlex.split(BASE)
print(f"{1 - float(a[a.index('--width') + 1]):.4f}", a[a.index('--swap-margin') + 1])
PY
)
read -r COMMON < <(python3 - <<'PY'
import pathlib, re
doc = pathlib.Path("docs/000_Ashare_workflow.md").read_text(encoding="utf-8")
m = re.search(r"# 2\. 构建 ROIC 带与逐日状态\n(.*?)\s+--out-bands", doc, re.S)
toks = [t for t in m.group(1).split() if t != "\\"]
assert toks[:2] == ["python3", "scripts/build_historical_valuation_bands.py"], toks[:3]
print(" ".join(toks[2:]))
PY
)
read -r PROD_DIVS < <(python3 - <<'PY'
import pathlib, re
doc = pathlib.Path("docs/000_Ashare_workflow.md").read_text(encoding="utf-8")
print(re.search(r"rebuild_bank_bands\.py divspread:([0-9.]+)", doc).group(1))
PY
)
[ "$DIVS" = "-" ] && DIVS="$PROD_DIVS"
echo "在册买入线 $BASE_LINE／换仓边际 $BASE_MARGIN；§6.7 第 2 步公共开关：$COMMON；divspread $DIVS"

if [ "$EXTRA" != "-" ]; then
  echo "=== [$(date +%T)] $ARM 建带（候选侧＋B2 并发）：$EXTRA ==="
  # shellcheck disable=SC2086
  RK_STMT_GAP_LOG="$E/gaps_base.csv" python3 scripts/build_historical_valuation_bands.py $COMMON $EXTRA \
    --out-bands "$E/roic_bands.csv" --out-daily "$E/roic_daily_raw.csv" > "$E/build_base.log" 2>&1 &
  P1=$!
  # shellcheck disable=SC2086
  RK_STMT_GAP_LOG="$E/gaps_b2.csv" python3 scripts/build_historical_valuation_bands.py $COMMON $EXTRA \
    --ttm-trust on --ttm-trust-delta 0.02 \
    --out-bands "$E/roic_bands_b2.csv" --out-daily "$E/roic_daily_raw_b2.csv" > "$E/build_b2.log" 2>&1 &
  P2=$!
  wait $P1 $P2
  RAW="$E/roic_daily_raw.csv"; RAW2="$E/roic_daily_raw_b2.csv"; BANDS="$E/roic_bands.csv"; BANDS2="$E/roic_bands_b2.csv"
elif [ "$DIVS_ARG" != "-" ]; then
  echo "=== [$(date +%T)] $ARM 只重跑第 3 步（读生产 raw 逐日）：divspread $DIVS ==="
  RAW="$S/roic_daily_raw.csv"; RAW2="$S/roic_daily_raw_b2.csv"; BANDS="$S/roic_bands.csv"; BANDS2="$S/roic_bands_b2.csv"
elif [ "$PANEL" != "-" ]; then
  echo "=== [$(date +%T)] $ARM 只对换宇宙重解买入线：$PANEL ==="
  python3 scripts/experimental/align_buy_line.py "$S/a_share_daily_states_adopted.csv" "$S/a_share_daily_states_adopted.csv" \
    --base-line "$BASE_LINE" --swap-margin "$BASE_MARGIN" --panel "$PANEL" | tee "$E/align_buy_line.txt"
  echo "=== [$(date +%T)] $ARM 完成 ==="
  exit 0
else
  echo "参数无效：建带开关、divspread、宇宙面板至少给一项" >&2; exit 2
fi

echo "=== [$(date +%T)] $ARM 银行/保险股利折现覆盖（两侧）==="
python3 scripts/rebuild_bank_bands.py "divspread:$DIVS" "$E/states_base.csv" "$RAW" "$BANDS" > "$E/bank_base.log" 2>&1 &
P3=$!
python3 scripts/rebuild_bank_bands.py "divspread:$DIVS" "$E/states_b2.csv" "$RAW2" "$BANDS2" > "$E/bank_b2.log" 2>&1 &
P4=$!
wait $P3 $P4

echo "=== [$(date +%T)] $ARM 合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py --base "$E/states_base.csv" --b2 "$E/states_b2.csv" --out "$E/states_hold.csv"

echo "=== [$(date +%T)] $ARM 买入线重解到同一在册合格面（§12.30）==="
python3 scripts/experimental/align_buy_line.py "$S/a_share_daily_states_adopted.csv" "$E/states_base.csv" \
  --base-line "$BASE_LINE" --swap-margin "$BASE_MARGIN" | tee "$E/align_buy_line.txt"

rm -f "$E/roic_daily_raw.csv" "$E/roic_daily_raw_b2.csv"
echo "=== [$(date +%T)] $ARM 完成 ==="

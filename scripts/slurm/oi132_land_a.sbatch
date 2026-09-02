#!/bin/bash
#SBATCH -J rk_oi132a
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-132 落地（上半）：购买法收购当年分子年化（consolidation_events.csv，现登记广东宏大 2025 年四笔）。
# 跑 §6.7 第 2／2b／3 步重建生产带与逐日状态，末尾按 §12.30 对旧状态文件重解买入线（只报数，不改常量）。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
S=data/processed
EXP=data/processed/experiments/exp_oi132_consolidation
COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
  --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
  --roic-trail-weight 0 --minority-basis earnings"

echo "=== [$(date +%T)] 0/ 保留旧状态文件供买入线重解对照 ==="
cp -f $S/a_share_daily_states_adopted.csv $EXP/a_share_daily_states_pre_oi132.csv
cp -f $S/roic_bands.csv $EXP/roic_bands_pre_oi132.csv

echo "=== [$(date +%T)] 2/ 候选侧建带 ==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --out-bands $S/roic_bands.csv --out-daily $S/roic_daily_raw.csv
echo "=== [$(date +%T)] 2b/ B2 建带 ==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands $S/roic_bands_b2.csv --out-daily $S/roic_daily_raw_b2.csv
echo "=== [$(date +%T)] 2 末/ 缺口文件核对 ==="
python3 - <<'PY'
import csv, pathlib
for f in ("data/interim/statement_coverage_gaps.csv", "data/interim/valuation_statement_gaps.csv"):
    p = pathlib.Path(f); n = sum(1 for _ in csv.DictReader(p.open(encoding="utf-8-sig"))) if p.exists() else 0
    print(f"  {f}: {n} 行")
PY

echo "=== [$(date +%T)] 3/ 银行/保险股利折现覆盖（候选侧、B2）==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_adopted.csv $S/roic_daily_raw.csv $S/roic_bands.csv
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_b2.csv $S/roic_daily_raw_b2.csv $S/roic_bands_b2.csv
echo "=== [$(date +%T)] 3 末/ 合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py

echo "=== [$(date +%T)] 买入线重解（§12.30，旧 1.0453／换仓边际 0.18）==="
python3 scripts/experimental/align_buy_line.py $EXP/a_share_daily_states_pre_oi132.csv $S/a_share_daily_states_adopted.csv \
  --base-line 1.0453 --swap-margin 0.18 | tee "$EXP/align_buy_line.txt"

echo "=== [$(date +%T)] 带值对比（旧 vs 新，只列变化行）==="
python3 - <<'PY'
import csv
def load(p):
    out = {}
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        out[(r.get("security_code") or "").zfill(6)] = r
    return out
a = load("data/processed/experiments/exp_oi132_consolidation/roic_bands_pre_oi132.csv"); b = load("data/processed/roic_bands.csv")
keys = [k for k in ("fair_value", "value", "nopat_ps", "roic0", "g0") if a and k in next(iter(a.values()))]
changed = 0
for code in sorted(set(a) | set(b)):
    ra, rb = a.get(code), b.get(code)
    if ra is None or rb is None or any(ra.get(k) != rb.get(k) for k in keys):
        changed += 1
        if changed <= 40:
            print("  ", code, {k: (ra.get(k) if ra else None, rb.get(k) if rb else None) for k in keys})
print(f"  变化行 {changed}／{len(b)}（比较列 {keys}）")
PY
echo "=== [$(date +%T)] 完成 ==="

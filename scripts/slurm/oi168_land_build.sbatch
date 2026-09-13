#!/bin/bash
#SBATCH -J rk_oi168build
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 02:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-168 落地（v4.169）：§6.7 第 2／2b／3 步在冻结输入上全市场重建生产逐日状态，营运资金口径 operating。
# 不跑第 1 步（输入纪元与 exp_oi168_wc_20260909 相同，令变化只归因于口径）；第 4 步起由 oi168_land_scan.sbatch 继续。

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
EXP=data/experiments/exp_oi168_land_20260909
S=data/processed

echo "=== [$(date +%T)] 旧生产文件指纹 ==="
python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
out = {}
for name in ("roic_bands.csv", "roic_bands_b2.csv", "a_share_daily_states_adopted.csv",
             "a_share_daily_states_b2.csv", "a_share_daily_states_hold.csv"):
    p = Path("data/processed") / name
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    out[name] = {"bytes": p.stat().st_size, "sha256": h.hexdigest(), "mtime": int(p.stat().st_mtime)}
Path("data/experiments/exp_oi168_land_20260909/pre_landing_production.json").write_text(
    json.dumps({"job": os.environ.get("SLURM_JOB_ID"), "files": out}, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(out, indent=1))
PY

# §6.7 第 2 步命令（与工作流正文逐字一致；--wc-aggregation operating 为 v4.169 生产口径）
COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
  --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
  --roic-trail-weight 0 --minority-basis earnings --wc-aggregation operating"

echo "=== [$(date +%T)] 第 2 步：候选侧建带 ==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --out-bands $S/roic_bands.csv --out-daily $S/roic_daily_raw.csv
if [ -s data/interim/valuation_statement_gaps.csv ] && [ "$(wc -l < data/interim/valuation_statement_gaps.csv)" -gt 1 ]; then
  echo "第 2 步三表覆盖缺口非空（data/interim/valuation_statement_gaps.csv），第 6 步按 §6.7 判 blocking" >&2
  cat data/interim/valuation_statement_gaps.csv >&2
fi

echo "=== [$(date +%T)] 第 2b 步：B2 建带 ==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands $S/roic_bands_b2.csv --out-daily $S/roic_daily_raw_b2.csv

echo "=== [$(date +%T)] 第 3 步：银行/保险股利折现覆盖 ==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_adopted.csv $S/roic_daily_raw.csv $S/roic_bands.csv
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_b2.csv $S/roic_daily_raw_b2.csv $S/roic_bands_b2.csv
echo "=== [$(date +%T)] 第 3 步末：合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py

echo "=== [$(date +%T)] 面板子集与实验 WCOP 状态逐位核对 ==="
python3 - <<'PY'
import csv, hashlib, json
from pathlib import Path
EXP = Path("data/experiments/exp_oi168_land_20260909")
codes = {l.strip() for l in Path("data/experiments/exp_oi168_wc_20260909/codes.txt").read_text().splitlines() if l.strip()}
def digest(path, subset):
    h, n = hashlib.sha256(), 0
    with path.open(newline="") as f:
        r = csv.reader(f); header = next(r); i = header.index("security_code")
        h.update((",".join(header) + "\n").encode())
        for row in r:
            if subset is None or row[i] in codes:
                h.update((",".join(row) + "\n").encode()); n += 1
    return {"sha256": h.hexdigest(), "rows": n}
out = []
for side, prod in (("base", "a_share_daily_states_adopted.csv"), ("hold", "a_share_daily_states_hold.csv")):
    a = digest(Path("data/experiments/exp_oi168_wc_20260909/val/WCOP") / f"states_{side}.csv", None)
    b = digest(Path("data/processed") / prod, codes)
    out.append({"side": side, "experiment": a, "production_subset": b, "equal": a == b})
(EXP / "production_equivalence.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(out, indent=1))
assert all(x["equal"] for x in out), "生产子集与实验 WCOP 状态不一致"
PY
echo "=== [$(date +%T)] 完成 ==="
ls -la $S/roic_bands.csv $S/roic_bands_b2.csv $S/a_share_daily_states_adopted.csv $S/a_share_daily_states_b2.csv $S/a_share_daily_states_hold.csv

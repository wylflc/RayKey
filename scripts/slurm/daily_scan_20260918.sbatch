#!/bin/bash
#SBATCH -J rk_scan_0918
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 00:20:00
#SBATCH --mem-per-cpu=1792M
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
if [[ "${SCAN_STAGE:-}" == "preview" ]]; then
  python3 scripts/fetch_equity_bond_inputs.py --refresh
  python3 scripts/fetch_cost_of_equity_inputs.py
  python3 scripts/screen_daily_volume_price_signals.py --as-of "${SCAN_DATE:?}" --workers 16 \
    --output-csv "data/interim/daily_quote_preview_${SCAN_DATE}.csv"
elif [[ "${SCAN_STAGE:-}" == "events" ]]; then
  python3 scripts/fetch_daily_market_evidence.py --as-of "${SCAN_DATE:?}" --since "${SCAN_SINCE:?}"
else
  bash scripts/slurm/daily_postclose.sbatch
fi

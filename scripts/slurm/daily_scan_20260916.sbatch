#!/bin/bash
#SBATCH -J rk_scan_0916
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 00:15:00
#SBATCH --mem-per-cpu=1792M
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
if [[ "${SCAN_STAGE:-}" == "events" ]]; then
  python3 scripts/fetch_daily_market_evidence.py --as-of "${SCAN_DATE:?}" --since "${SCAN_SINCE:?}"
elif [[ "${SCAN_STAGE:-}" == "evidence_retry" ]]; then
  # Job 26779088 completed disclosures, forecasts and all action queries except
  # the single 688981 rights-history request. Retry that request, then resume.
  python3 scripts/fetch_ohlcv_history.py --signal-date "${SCAN_DATE:?}" --rights-only \
    --codes-file data/interim/daily_action_retry_codes_2026-09-16.txt --timeout 45
  python3 scripts/fetch_daily_market_evidence.py --as-of "$SCAN_DATE" --since "${SCAN_SINCE:?}"
  python3 scripts/daily_execution_guard.py evidence --as-of "$SCAN_DATE" --since "$SCAN_SINCE"
  python3 scripts/build_report_update_queue.py --market A_SHARE --signal-date "$SCAN_DATE"
elif [[ "${SCAN_STAGE:-}" == "preview" ]]; then
  python3 scripts/fetch_equity_bond_inputs.py --refresh
  python3 scripts/fetch_cost_of_equity_inputs.py
  python3 scripts/screen_daily_volume_price_signals.py --as-of "${SCAN_DATE:?}" --workers 16 \
    --output-csv "data/interim/daily_quote_preview_${SCAN_DATE}.csv"
else
  bash scripts/slurm/daily_postclose.sbatch
fi

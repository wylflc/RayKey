#!/bin/bash
# Refresh workflow §6.7 steps 4–6 from existing financial bands, after evidence
# confirms no new financial report. Useful for daily ex-dividend normalization.
# This does not replace the full rebuild required by a financial update queue.
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=refresh_pool
#SBATCH --output=logs/refresh_pool_%j.out
#SBATCH --error=logs/refresh_pool_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
: "${SIGNAL_DATE:?Set SIGNAL_DATE}"
: "${SINCE:?Set previous successful scan date}"
python3 scripts/build_pool_model_bands.py --signal-date "$SIGNAL_DATE"
python3 scripts/apply_forecast_band_overlay.py --signal-date "$SIGNAL_DATE"
python3 scripts/build_pool_model_bands.py --signal-date "$SIGNAL_DATE" --bands data/processed/roic_bands_b2.csv --states data/processed/a_share_daily_states_b2.csv --out data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/apply_forecast_band_overlay.py --signal-date "$SIGNAL_DATE" --bands data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/build_hold_model_bands.py --signal-date "$SIGNAL_DATE"
python3 scripts/apply_model_bands_to_dossiers.py --signal-date "$SIGNAL_DATE"
python3 scripts/build_valuation_band_cards.py --tags data/interim/strategy_tag_map.csv --out data/interim/valuation_band_cards.csv --signal-date "$SIGNAL_DATE"
python3 scripts/apply_valuation_band_cards.py --signal-date "$SIGNAL_DATE" --quotes skip
python3 scripts/audit_financial_panel_consistency.py --signal-date "$SIGNAL_DATE"
python3 scripts/validate_valuation_bands.py --valuation data/processed/a_share_focus_watchlist_l1_l2_valuation.csv --queue-out data/interim/valuation_rebuild_queue.csv --signal-date "$SIGNAL_DATE"
python3 scripts/build_a_share_core_valuation_pool.py --signal-date "$SIGNAL_DATE"
python3 scripts/build_company_dossier_readmes.py --check
python3 scripts/build_report_update_queue.py --market A_SHARE --signal-date "$SIGNAL_DATE"
python3 scripts/daily_execution_guard.py evidence --as-of "$SIGNAL_DATE" --since "$SINCE"

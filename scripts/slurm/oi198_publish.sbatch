#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=oi198_publish
#SBATCH --output=logs/oi198_publish_%j.out
#SBATCH --error=logs/oi198_publish_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
/usr/bin/time -v python3 data/experiments/exp_oi198_20260921/publish.py
python3 data/experiments/exp_oi198_20260921/register.py
python3 scripts/build_pool_model_bands.py --signal-date 2026-09-21
python3 scripts/apply_forecast_band_overlay.py --signal-date 2026-09-21
python3 scripts/build_pool_model_bands.py --signal-date 2026-09-21 --bands data/processed/roic_bands_b2.csv --states data/processed/a_share_daily_states_b2.csv --out data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/apply_forecast_band_overlay.py --signal-date 2026-09-21 --bands data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/build_hold_model_bands.py --signal-date 2026-09-21
python3 scripts/apply_model_bands_to_dossiers.py --signal-date 2026-09-21
python3 scripts/build_valuation_band_cards.py --tags data/interim/strategy_tag_map.csv --out data/interim/valuation_band_cards.csv --signal-date 2026-09-21
python3 scripts/apply_valuation_band_cards.py --signal-date 2026-09-21 --quotes skip
python3 scripts/audit_financial_panel_consistency.py --signal-date 2026-09-21
python3 scripts/validate_valuation_bands.py --valuation data/processed/a_share_focus_watchlist_l1_l2_valuation.csv --queue-out data/interim/valuation_rebuild_queue.csv --signal-date 2026-09-21
python3 scripts/build_a_share_core_valuation_pool.py --signal-date 2026-09-21
python3 scripts/build_company_dossier_readmes.py --check
python3 scripts/check_swap_margin_scale_drift.py
python3 scripts/build_report_update_queue.py --market A_SHARE --signal-date 2026-09-21
python3 scripts/daily_execution_guard.py evidence --as-of 2026-09-21 --since 2026-09-18
python3 data/experiments/exp_oi198_20260921/scan.py
python3 data/experiments/exp_oi198_20260921/finish.py

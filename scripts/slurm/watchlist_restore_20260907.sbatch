#!/bin/bash
#SBATCH -J rk_restore_0907
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 同日财务、全市场模型和逐日状态已完成重建；只按用户裁定同步池成员。
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
RESOLUTION_DATE=2026-09-07
PROCESSED=data/processed

python3 scripts/build_pool_model_bands.py --signal-date "$RESOLUTION_DATE"
python3 scripts/apply_forecast_band_overlay.py --signal-date "$RESOLUTION_DATE"
python3 scripts/build_pool_model_bands.py --signal-date "$RESOLUTION_DATE" \
    --bands "$PROCESSED/roic_bands_b2.csv" --states "$PROCESSED/a_share_daily_states_b2.csv" \
    --out "$PROCESSED/a_share_pool_model_bands_b2.csv"
python3 scripts/apply_forecast_band_overlay.py --signal-date "$RESOLUTION_DATE" \
    --bands "$PROCESSED/a_share_pool_model_bands_b2.csv"
python3 scripts/build_hold_model_bands.py
python3 scripts/apply_model_bands_to_dossiers.py --signal-date "$RESOLUTION_DATE"
python3 scripts/build_company_dossier_readmes.py
python3 scripts/build_valuation_band_cards.py --tags data/interim/strategy_tag_map.csv \
    --out data/interim/valuation_band_cards.csv --signal-date "$RESOLUTION_DATE"
python3 scripts/apply_valuation_band_cards.py --signal-date "$RESOLUTION_DATE" --quotes fetch
# 核对新成员集合，不能使用尚未重建的旧核心池作为审核范围。
python3 scripts/audit_financial_panel_consistency.py --signal-date "$RESOLUTION_DATE" \
    --pool data/interim/moat_reaudit_2026-09-07/user_resolution_pool.csv
python3 scripts/validate_valuation_bands.py \
    --valuation "$PROCESSED/a_share_focus_watchlist_l1_l2_valuation.csv" \
    --queue-out data/interim/valuation_rebuild_queue.csv --signal-date "$RESOLUTION_DATE"
python3 scripts/build_a_share_core_valuation_pool.py --signal-date "$RESOLUTION_DATE" --quotes fetch
python3 scripts/build_moat_panel.py --today "$RESOLUTION_DATE"
python3 scripts/build_company_dossier_readmes.py
python3 scripts/build_company_dossier_readmes.py --check

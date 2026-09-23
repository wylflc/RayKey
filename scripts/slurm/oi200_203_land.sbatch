#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi200_land
#SBATCH --output=logs/oi200_land_%j.out
#SBATCH --error=logs/oi200_land_%j.err
# OI-200～203 落地：安装 NEW 历史状态 → §6.7 第 4～7 步（信号日 2026-09-23）→ BASE 同键重登 → 重发当日执行清单 → 终检
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi200_203_20260923
D=2026-09-23
(cd $E && /usr/bin/time -v python3 publish.py && python3 register.py)
python3 scripts/build_pool_model_bands.py --signal-date $D
python3 scripts/apply_forecast_band_overlay.py --signal-date $D
python3 scripts/build_pool_model_bands.py --signal-date $D --bands data/processed/roic_bands_b2.csv --states data/processed/a_share_daily_states_b2.csv --out data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/apply_forecast_band_overlay.py --signal-date $D --bands data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/build_hold_model_bands.py --signal-date $D
python3 scripts/apply_model_bands_to_dossiers.py --signal-date $D
python3 scripts/build_valuation_band_cards.py --tags data/interim/strategy_tag_map.csv --out data/interim/valuation_band_cards.csv --signal-date $D
python3 scripts/apply_valuation_band_cards.py --signal-date $D --quotes skip
python3 scripts/audit_financial_panel_consistency.py --signal-date $D
python3 scripts/validate_valuation_bands.py --valuation data/processed/a_share_focus_watchlist_l1_l2_valuation.csv --queue-out data/interim/valuation_rebuild_queue.csv --signal-date $D
python3 scripts/build_a_share_core_valuation_pool.py --signal-date $D
python3 scripts/build_company_dossier_readmes.py --check
python3 scripts/check_swap_margin_scale_drift.py || echo "DRIFT_GUARD_NONZERO"
python3 scripts/build_report_update_queue.py --market A_SHARE --signal-date $D
python3 scripts/daily_execution_guard.py evidence --as-of $D --since 2026-09-22
(cd $E && python3 scan.py && python3 finish.py)

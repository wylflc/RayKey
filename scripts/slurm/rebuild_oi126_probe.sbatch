#!/bin/bash
#SBATCH -J rk_oi126b
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-126 通用修复后：三大报表探针重取 252 只（6 只关键值实变）＋中国神华 FY2025 bps 重述订正入库，按 §6.7 第 2~7 步全链重建。
# 参数与 v4.120/v4.121 生产链逐项相同（W=0），**只有输入数据变了**，故直接写生产文件名。
# 第 1 步不重跑：财务输入沿用本日 §7.1 那批，与订正同源，保持单变量。

set -uo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
D=2026-09-01
P=data/processed

run() { echo "=== [$(date +%T)] $* ==="; "$@" || { echo "!!! 失败：$*"; exit 1; }; }

COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
 --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid \
 --roic-cycle-guard peak --roic-cond-detect graded --roic-peak-ramp 0.3 \
 --ttm-current on --growth-damp on --thin-equity-max 0.5 --roic-trail-weight 0"

run python3 scripts/build_historical_valuation_bands.py $COMMON \
  --out-bands $P/roic_bands.csv --out-daily $P/roic_daily_raw.csv
run python3 scripts/build_historical_valuation_bands.py $COMMON --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands $P/roic_bands_b2.csv --out-daily $P/roic_daily_raw_b2.csv

run python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $P/a_share_daily_states_adopted.csv $P/roic_daily_raw.csv $P/roic_bands.csv
run python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $P/a_share_daily_states_b2.csv $P/roic_daily_raw_b2.csv $P/roic_bands_b2.csv
run python3 scripts/build_hold_daily_states.py

run python3 scripts/build_pool_model_bands.py --signal-date $D
run python3 scripts/apply_forecast_band_overlay.py --signal-date $D
run python3 scripts/build_pool_model_bands.py --signal-date $D \
      --bands $P/roic_bands_b2.csv --states $P/a_share_daily_states_b2.csv \
      --out $P/a_share_pool_model_bands_b2.csv
run python3 scripts/apply_forecast_band_overlay.py --signal-date $D --bands $P/a_share_pool_model_bands_b2.csv
run python3 scripts/build_hold_model_bands.py
run python3 scripts/apply_model_bands_to_dossiers.py --signal-date $D
run python3 scripts/build_company_dossier_readmes.py

run python3 scripts/build_valuation_band_cards.py \
      --tags data/interim/strategy_tag_map.csv \
      --out data/interim/valuation_band_cards.csv --signal-date $D
run python3 scripts/apply_valuation_band_cards.py --signal-date $D --quotes fetch

echo "=== [$(date +%T)] 第 5.5 步 面板自洽核对 ==="
python3 scripts/audit_financial_panel_consistency.py --signal-date $D || exit $?

run python3 scripts/validate_valuation_bands.py \
      --valuation $P/a_share_focus_watchlist_l1_l2_valuation.csv \
      --queue-out data/interim/valuation_rebuild_queue.csv --signal-date $D
run python3 scripts/build_a_share_core_valuation_pool.py --signal-date $D

echo "=== [$(date +%T)] 第 7 步 换仓边际标度漂移守卫 ==="
python3 scripts/check_swap_margin_scale_drift.py
echo "=== [$(date +%T)] 全部完成（守卫退出码 $?）==="

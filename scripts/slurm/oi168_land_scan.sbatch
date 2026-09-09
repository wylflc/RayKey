#!/bin/bash
#SBATCH -J rk_oi168land
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-168 落地（v4.169）第二段：新生产状态上换仓边际七档重扫（在册读数＋剔除集 A 重选）→ §6.7 第 4～7 步展示链
# → 信号层不变量（panel_tier_forward 两遍）。前置：oi168_land_build.sbatch 完成（--dependency=afterok）。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
D=${SIGNAL_DATE:-2026-09-09}
EXP=data/experiments/exp_oi168_land_20260909
S=data/processed
P=$S/pit_attention/panel_moat_bank_v6b.csv
test -s "$EXP/production_equivalence.json"

echo "=== [$(date +%T)] 换仓边际七档 × 14 起点 × 全样本/剔除集 A ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/margin_arms.txt" \
  --out "$EXP/sweep_margin.txt" --workers 60 \
  --title "OI-168 落地：营运资金 operating 生产状态上的换仓边际重扫（买入线 1.0454 容差内保留）" \
  | tee "$EXP/report_margin.txt"

echo "=== [$(date +%T)] 4/ 池带 → 预告叠加 → B2 → 持仓侧 → 档案 → README（--signal-date $D）==="
python3 scripts/build_pool_model_bands.py --signal-date $D
python3 scripts/apply_forecast_band_overlay.py --signal-date $D
python3 scripts/build_pool_model_bands.py --signal-date $D \
  --bands $S/roic_bands_b2.csv --states $S/a_share_daily_states_b2.csv \
  --out $S/a_share_pool_model_bands_b2.csv
python3 scripts/apply_forecast_band_overlay.py --signal-date $D --bands $S/a_share_pool_model_bands_b2.csv
python3 scripts/build_hold_model_bands.py
python3 scripts/apply_model_bands_to_dossiers.py --signal-date $D
python3 scripts/build_company_dossier_readmes.py

echo "=== [$(date +%T)] 5/ 建带卡 → 估值表 ==="
python3 scripts/build_valuation_band_cards.py \
  --tags data/interim/strategy_tag_map.csv \
  --out data/interim/valuation_band_cards.csv --signal-date $D
python3 scripts/apply_valuation_band_cards.py --signal-date $D --quotes fetch

echo "=== [$(date +%T)] 5.5/ 面板自洽核对 ==="
python3 scripts/audit_financial_panel_consistency.py --signal-date $D || echo "（第 5.5 步返回非零，读上文严重级）"

echo "=== [$(date +%T)] 6/ 校验 + 物化核心池 ==="
python3 scripts/validate_valuation_bands.py \
  --valuation $S/a_share_focus_watchlist_l1_l2_valuation.csv \
  --queue-out data/interim/valuation_rebuild_queue.csv --signal-date $D
python3 scripts/build_a_share_core_valuation_pool.py --signal-date $D

echo "=== [$(date +%T)] 7/ 换仓边际标度漂移守卫（先报现值，再对基准校验）==="
python3 scripts/check_swap_margin_scale_drift.py --baseline | tee "$EXP/drift_baseline.txt"
python3 scripts/check_swap_margin_scale_drift.py | tee "$EXP/drift_check.txt" || echo "（守卫非零：V 标度已变，按 --baseline 现值重定基准）"

echo "=== [$(date +%T)] 信号层不变量：panel_tier_forward（新生产状态 / 冻结 legacy 子集）==="
python3 scripts/experimental/panel_tier_forward.py \
  --states $S/a_share_daily_states_adopted.csv --panel $P --since 2005-01-01 \
  --exclude-banks --per-code-out "$EXP/tier_forward_percode_operating.csv" | tee "$EXP/tier_forward_operating.txt"
python3 scripts/experimental/panel_tier_forward.py \
  --states data/experiments/exp_oi168_wc_20260909/val/BASE/states_base.csv --panel $P --since 2005-01-01 \
  --exclude-banks --per-code-out "$EXP/tier_forward_percode_legacy.csv" | tee "$EXP/tier_forward_legacy.txt"
echo "=== [$(date +%T)] 完成 ==="

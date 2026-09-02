#!/bin/bash
#SBATCH -J rk_oi128130land
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-128／129／130 落地：NEW 臂产物已复制为生产文件、买入线与换仓边际已改入生产常量与 BASE。
# 本作业跑 §6.7 第 4~7 步（展示层全链）＋ 新基准单臂重扫（在册读数重登、剔除集 A 重选）＋ §6.8 海外链。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
D=${SIGNAL_DATE:-2026-09-02}
EXP=data/processed/experiments/exp_oi128_130_adopt
S=data/processed

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
python3 scripts/check_swap_margin_scale_drift.py || echo "（守卫非零：V 标度已变，按 --baseline 现值重定基准）"

echo "=== [$(date +%T)] 新基准单臂重扫（在册读数＋剔除集 A 重选）==="
printf '# OI-128/129/130 落地后新在册基准\nBASE|\n' > "$EXP/configs/base_only.txt"
python3 scripts/sweep_backtest_configs.py "$EXP/configs/base_only.txt" \
  --out "$EXP/sweep_newbase.txt" --workers 28 \
  --title "OI-128/129/130 落地后新在册基准" | tee "$EXP/report_newbase.txt"

echo "=== [$(date +%T)] §6.8 海外链（股权桥同口径）==="
python3 scripts/build_overseas_roic_bands.py --as-of $D --quotes fetch | tail -25 || echo "（海外链失败，读上文）"
echo "=== [$(date +%T)] 完成 ==="

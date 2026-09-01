#!/bin/bash
#SBATCH -J rk_w0_disp
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-124 收口：§6.7 第 4~6 步按现有基准（W=0 链）重建展示层。
# 第 1 步不重跑——财务输入沿用 8-31 那批，与今日重建的带同源，保持单变量。
# 第 7 步已单独跑过（漂移 +0.0000，未超限）。
# 第 5.5 步只报不改：报「严重」即停在第 6 步之前，不物化核心池。

set -uo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
D=2026-09-01          # 北京日期（TZ=Asia/Shanghai）
P=data/processed

run() { echo "=== [$(date +%T)] $* ==="; "$@" || { echo "!!! 失败：$*"; exit 1; }; }

# --- 第 4 步：池模型带 → 预告叠加 →（B2 同两步 → 持仓侧池带）→ 逐票档案 → README ---
run python3 scripts/build_pool_model_bands.py --signal-date $D
run python3 scripts/apply_forecast_band_overlay.py --signal-date $D
run python3 scripts/build_pool_model_bands.py --signal-date $D \
      --bands $P/roic_bands_b2.csv --states $P/a_share_daily_states_b2.csv \
      --out $P/a_share_pool_model_bands_b2.csv
run python3 scripts/apply_forecast_band_overlay.py --signal-date $D --bands $P/a_share_pool_model_bands_b2.csv
run python3 scripts/build_hold_model_bands.py
run python3 scripts/apply_model_bands_to_dossiers.py --signal-date $D
run python3 scripts/build_company_dossier_readmes.py

# --- 第 5 步：档案 → 建带卡 → 估值表 ---
run python3 scripts/build_valuation_band_cards.py \
      --tags data/interim/strategy_tag_map.csv \
      --out data/interim/valuation_band_cards.csv --signal-date $D
run python3 scripts/apply_valuation_band_cards.py --signal-date $D --quotes fetch

# --- 第 5.5 步：面板自洽核对（只报不改；「严重」须逐条处置后才继续）---
echo "=== [$(date +%T)] 第 5.5 步 面板自洽核对 ==="
python3 scripts/audit_financial_panel_consistency.py --signal-date $D
AUDIT=$?
if [ $AUDIT -ne 0 ]; then
  echo "!!! 第 5.5 步退出码 $AUDIT —— 按 §6.7 停在第 6 步之前，核心池未物化。先逐条处置再单跑第 6 步。"
  exit $AUDIT
fi

# --- 第 6 步：校验并物化核心池 ---
run python3 scripts/validate_valuation_bands.py \
      --valuation $P/a_share_focus_watchlist_l1_l2_valuation.csv \
      --queue-out data/interim/valuation_rebuild_queue.csv --signal-date $D
run python3 scripts/build_a_share_core_valuation_pool.py --signal-date $D

echo "=== [$(date +%T)] 全部完成 ==="

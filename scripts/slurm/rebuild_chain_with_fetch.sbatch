#!/bin/bash
#SBATCH -J rk_chain_fetch
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §6.7 估值重建链的第 1 步（刷新财务输入与除权事件）＋第 2 / 2b / 3 步（重建逐日估值状态）。
# 计算节点可访问外网，抓取与建带放同一作业串行完成；第 4 步起在交互节点按 §6.7 继续。
#
# 用法：
#   sbatch --export=ALL,SIGNAL_DATE=YYYY-MM-DD,SINCE=<当前报告期末>[,EXTRA_CODES="600150 ..."] \
#     scripts/slurm/rebuild_chain_with_fetch.sbatch
# （环境变量前缀写法 `VAR=... sbatch` 在本机不传入作业，须用 --export）
# EXTRA_CODES：点名建档的池外代码，三大报表按 --codes 先行补取并入面板，再跑面板缺省名单。

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
: "${SIGNAL_DATE:?需要 SIGNAL_DATE=YYYY-MM-DD}"
: "${SINCE:?需要 SINCE=<当前报告期末>}"

echo "=== [$(date +%H:%M:%S)] 第 1 步：逐季财务 ==="
python3 scripts/fetch_a_share_quarterly_financials.py --signal-date "$SIGNAL_DATE" --since "$SINCE"

if [ -n "${EXTRA_CODES:-}" ]; then
  echo "=== [$(date +%H:%M:%S)] 第 1 步：点名代码三大报表补取（$EXTRA_CODES）==="
  # shellcheck disable=SC2086
  python3 scripts/fetch_a_share_financial_statements.py --signal-date "$SIGNAL_DATE" --codes $EXTRA_CODES
fi
echo "=== [$(date +%H:%M:%S)] 第 1 步：三大报表（面板缺省名单）==="
python3 scripts/fetch_a_share_financial_statements.py --signal-date "$SIGNAL_DATE"

echo "=== [$(date +%H:%M:%S)] 第 1 步：除权事件 ==="
python3 scripts/fetch_ohlcv_history.py --signal-date "$SIGNAL_DATE" --actions-only
echo "=== [$(date +%H:%M:%S)] 第 1 步：rf/ERP 序列 ==="
python3 scripts/fetch_cost_of_equity_inputs.py
echo "=== [$(date +%H:%M:%S)] 第 1 步：股本变动事件 ==="
python3 scripts/fetch_a_share_share_changes.py --signal-date "$SIGNAL_DATE"
echo "=== [$(date +%H:%M:%S)] 第 1 步：股债利差输入 ==="
python3 scripts/fetch_equity_bond_inputs.py --refresh

if [ -s data/interim/statement_coverage_gaps.csv ] && [ "$(wc -l < data/interim/statement_coverage_gaps.csv)" -gt 1 ]; then
  echo "三大报表覆盖缺口非空（data/interim/statement_coverage_gaps.csv），按 §6.7 先补取再继续" >&2
  cat data/interim/statement_coverage_gaps.csv >&2
  exit 1
fi

COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
  --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
  --roic-trail-weight 0 --minority-basis earnings"

echo "=== [$(date +%H:%M:%S)] 第 2 步：候选侧建带 ==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --out-bands data/processed/roic_bands.csv \
  --out-daily data/processed/roic_daily_raw.csv

echo "=== [$(date +%H:%M:%S)] 第 2b 步：B2 建带（与第 2 步串行）==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands data/processed/roic_bands_b2.csv \
  --out-daily data/processed/roic_daily_raw_b2.csv

echo "=== [$(date +%H:%M:%S)] 第 3 步：银行/保险股利折现覆盖 ==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_adopted.csv \
  data/processed/roic_daily_raw.csv \
  data/processed/roic_bands.csv
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_b2.csv \
  data/processed/roic_daily_raw_b2.csv \
  data/processed/roic_bands_b2.csv

echo "=== [$(date +%H:%M:%S)] 第 3 步末：合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py

echo "=== [$(date +%H:%M:%S)] 完成，产物： ==="
ls -la data/processed/roic_bands.csv data/processed/roic_daily_raw.csv \
       data/processed/roic_bands_b2.csv data/processed/roic_daily_raw_b2.csv \
       data/processed/a_share_daily_states_adopted.csv \
       data/processed/a_share_daily_states_b2.csv \
       data/processed/a_share_daily_states_hold.csv

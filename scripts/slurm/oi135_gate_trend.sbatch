#!/bin/bash
#SBATCH -J rk_gatetrend
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.174 追问：谷守卫放进买入线的谷年公司，走势闸门能不能把不复苏的那批挡掉（用户 2026-09-02 假设）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
python3 scripts/experimental/trough_gate_trend_check.py \
  --states data/processed/a_share_daily_states_adopted.csv --bands data/processed/roic_bands.csv \
  --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --buy-line 1.0454 --horizon 3 \
  --ledger "$EXP/why/BASE/ledger.csv" > "$EXP/trough_gate_trend_h3.txt"
python3 scripts/experimental/trough_gate_trend_check.py \
  --states data/processed/a_share_daily_states_adopted.csv --bands data/processed/roic_bands.csv \
  --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --buy-line 1.0454 --horizon 1 \
  > "$EXP/trough_gate_trend_h1.txt"
echo "=== [$(date +%T)] 完成 ==="

#!/bin/bash
#SBATCH -J rk_oi150b
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-150 补齐退市公司代码（XBRL 实例文件名回退）后的重跑：股票池（缓存）→ 新代码取价 → 逐月时点估值 → 报告。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
S=scripts/experimental/overseas_pv_forward.py
echo "=== [$(date +%T)] universe ==="; python3 $S universe --start-cy 2009 --end-cy 2019 --top 400
echo "=== [$(date +%T)] facts ==="; python3 $S facts
echo "=== [$(date +%T)] prices ==="; python3 $S prices --threads 3
echo "=== [$(date +%T)] value ==="; python3 $S value --workers 30
echo "=== [$(date +%T)] report ==="; python3 $S report
echo "=== [$(date +%T)] 完成 ==="

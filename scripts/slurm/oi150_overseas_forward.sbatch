#!/bin/bash
#SBATCH -J rk_oi150
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 10:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-150 美股估值信号预登记前向检验全链（预登记书 docs/reports/overseas_pv_forward_prereg.zh.md）：
# 股票池（SEC frames CY2009～2019 每年前 400 非金融）→ companyfacts → 腾讯日线 → 逐月时点估值 → 报告。取数在计算节点。
# 各步可续跑：原始数据与已取价格文件缓存复用；腾讯限流约 250 次请求／33 分钟，取价按实测约 40 只/小时留时限。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
S=scripts/experimental/overseas_pv_forward.py
echo "=== [$(date +%T)] universe ==="; python3 $S universe --start-cy 2009 --end-cy 2019 --top 400
echo "=== [$(date +%T)] facts ==="; python3 $S facts
echo "=== [$(date +%T)] prices ==="; python3 $S prices --threads 3
echo "=== [$(date +%T)] value ==="; python3 $S value --workers 30
echo "=== [$(date +%T)] report ==="; python3 $S report
echo "=== [$(date +%T)] 完成 ==="

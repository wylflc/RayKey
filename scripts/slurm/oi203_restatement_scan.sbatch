#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi203_scan
#SBATCH --output=logs/oi203_scan_%j.out
#SBATCH --error=logs/oi203_scan_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
/usr/bin/time -v python3 scripts/scan_restatement_announcements.py --history --since ${SINCE:-2009-01-01} --until ${UNTIL:-$(TZ=Asia/Shanghai date +%F)}

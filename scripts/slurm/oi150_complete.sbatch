#!/bin/bash
#SBATCH -J oi150_complete
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
if [ "${1:-all}" = all ]; then
    python3 scripts/experimental/oi150_complete.py prepare --fetch
elif [ "$1" != value ]; then
    echo 'usage: sbatch oi150_complete.sbatch [all|value]' >&2
    exit 2
fi
python3 scripts/experimental/oi150_complete.py value --workers 16
python3 scripts/experimental/oi150_complete.py report

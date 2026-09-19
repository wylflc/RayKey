#!/bin/bash
#SBATCH -J rk_rcanchor
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 scripts/experimental/residual_clear_anchors.py --labels "${LABELS:-BASE,RC150}"

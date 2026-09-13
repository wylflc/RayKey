#!/bin/bash
#SBATCH -J rk_whjoint
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
EXTRA_ARGS=()
if [[ "${SKIP_ARTIFACTS:-0}" == "1" ]]; then EXTRA_ARGS+=(--skip-artifacts); fi
python3 scripts/experimental/whipsaw_joint_run.py "${PHASE:-r1}" --workers "${WORKERS:-60}" "${EXTRA_ARGS[@]}"

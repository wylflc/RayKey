#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:30:00
#SBATCH --job-name=cbbi_temp
#SBATCH --output=logs/cbbi_temp_%j.out
#SBATCH --error=logs/cbbi_temp_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg
export MPLCONFIGDIR="${TMPDIR:-/tmp}/raykey_cbbi_mpl_${SLURM_JOB_ID}"
if [[ "${STAGE:-run}" == "fetch" ]]; then
    python3 -u scripts/experimental/cbbi_temperature_data.py
else
    python3 -u scripts/experimental/cbbi_temperature.py
    python3 -u scripts/experimental/cbbi_temperature_audit.py
fi

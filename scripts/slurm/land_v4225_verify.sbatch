#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=v4225_verify
#SBATCH --output=logs/land_v4225_verify_%j.out
#SBATCH --error=logs/land_v4225_verify_%j.err
# v4.225：NEW 对正式按保险行分流核对，并用落地口径（自然月末 Ḡ）重算 OI-232 预登记读数 1～4
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_land_v4225_20260930
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
/usr/bin/time -v python3 verify_new.py

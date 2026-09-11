#!/bin/bash
#SBATCH -J rk_riskbudget
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
task_exp=data/experiments/exp_risk_budget_20260911
python3 -m unittest discover -s "$task_exp" -p 'test_policy.py' > "$task_exp/tests.txt" 2>&1
if [[ "${RISK_PILOT:-0}" == 1 ]]; then
    python3 "$task_exp/run.py" --pilot --workers 4
else
    python3 "$task_exp/run.py" --workers 12
fi

#!/bin/bash
# OI-124：把 W=0 链换入生产文件名。现行 W=1.0 的七份改名留作 *_w100.bak，可整体回滚。
# 用法：cutover_w0_baseline.sh [--rollback]
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
P=data/processed
FILES="roic_bands roic_daily_raw roic_bands_b2 roic_daily_raw_b2 \
a_share_daily_states_adopted a_share_daily_states_b2 a_share_daily_states_hold"

if [ "${1:-}" = "--rollback" ]; then
  for f in $FILES; do
    [ -f "$P/${f}_w100.bak.csv" ] || { echo "缺 $P/${f}_w100.bak.csv，中止"; exit 1; }
  done
  for f in $FILES; do
    mv "$P/$f.csv" "$P/${f}_w0.csv"
    mv "$P/${f}_w100.bak.csv" "$P/$f.csv"
    echo "回滚 $f"
  done
  exit 0
fi

for f in $FILES; do
  [ -s "$P/${f}_w0.csv" ] || { echo "缺 $P/${f}_w0.csv 或为空，中止"; exit 1; }
done
echo "— 换入前行数核对 —"
for f in a_share_daily_states_adopted a_share_daily_states_hold; do
  printf "%-34s W1=%s  W0=%s\n" "$f" "$(wc -l < "$P/$f.csv")" "$(wc -l < "$P/${f}_w0.csv")"
done
for f in $FILES; do
  mv "$P/$f.csv" "$P/${f}_w100.bak.csv"
  mv "$P/${f}_w0.csv" "$P/$f.csv"
  echo "换入 $f"
done

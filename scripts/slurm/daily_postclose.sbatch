#!/bin/bash
#SBATCH -J rk_postclose
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
: "${SCAN_DATE:?Set SCAN_DATE to the signal date}"
: "${SCAN_STAGE:?Set SCAN_STAGE to evidence or scan}"

case "$SCAN_STAGE" in
  evidence)
    : "${SCAN_REPORT_DATE:?Set SCAN_REPORT_DATE to the latest reporting period}"
    python3 scripts/fetch_a_share_report_disclosures.py --report-date "$SCAN_REPORT_DATE" --output data/interim/a_share_report_disclosures.csv
    python3 scripts/fetch_a_share_earnings_forecasts.py --report-date "$SCAN_REPORT_DATE" --output data/interim/a_share_earnings_forecasts.csv
    python3 scripts/build_report_update_queue.py --market A_SHARE --signal-date "$SCAN_DATE"
    python3 - <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, 'scripts')
from screen_daily_volume_price_signals import fetch_daily_rows, add_indicators

date = os.environ['SCAN_DATE']
result = {}
for code in filter(None, os.environ.get('SCAN_ENTRY_CODES', '').split(',')):
    exchange = 'SSE' if code.startswith('6') else 'SZSE'
    source, rows = fetch_daily_rows(code, exchange, date, 15.0)
    rows = [r for r in rows if r['date'] <= date]
    assert rows and rows[-1]['date'] == date, (code, 'missing execution-day quote')
    add_indicators(rows)
    latest = rows[-1]
    assert latest.get('ma60') or latest.get('ma20'), (code, 'no stop anchor')
    result[code] = {
        'trade_date': date, 'source_url': source,
        'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
        'close': latest['close'], 'ma20': latest.get('ma20'), 'ma60': latest.get('ma60'),
        'entry_stop_price': latest.get('ma60') or latest['ma20'],
        'recent_closes': [{'date': r['date'], 'close': r['close']} for r in rows[-60:]],
    }
path = Path('data/interim') / f'daily_entry_anchors_{date}.json'
path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print('Execution-day anchors:', {c: r['entry_stop_price'] for c, r in result.items()}, flush=True)
PY
    ;;
  scan)
    : "${SCAN_NAV:?Set SCAN_NAV from the account snapshot}"
    : "${SCAN_FUNDS:?Set SCAN_FUNDS from broker funds plus cash}"
    python3 scripts/check_report_day_price_divergence.py --as-of "$SCAN_DATE"
    python3 scripts/build_a_share_core_valuation_pool.py --md-only --quotes fetch --signal-date "$SCAN_DATE"
    python3 scripts/screen_daily_volume_price_signals.py --as-of "$SCAN_DATE" \
      --review-queue data/interim/a_share_report_update_queue.csv \
      --model-bands data/processed/a_share_pool_model_bands_adopted.csv \
      --hold-bands data/processed/a_share_pool_model_bands_hold.csv \
      --nav "$SCAN_NAV" --funds "$SCAN_FUNDS" --workers 16
    python3 scripts/track_holdings_daily.py --as-of "$SCAN_DATE"
    python3 scripts/check_report_day_price_divergence.py --as-of "$SCAN_DATE"
    ;;
  *) printf '%s\n' 'SCAN_STAGE must be evidence or scan' >&2; exit 2 ;;
esac

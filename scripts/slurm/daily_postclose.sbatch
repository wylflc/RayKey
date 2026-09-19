#!/bin/bash
#SBATCH -J rk_postclose
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH --mem-per-cpu=1792M
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
: "${SCAN_DATE:?Set SCAN_DATE to the signal date}"
: "${SCAN_STAGE:?Set SCAN_STAGE to evidence or scan}"

refresh_market_inputs() {
  # §9.3.1 股债总仓位上限读 equity_bond_csi300.csv（观测过期 45 天扫描报错）；银行/保险股利折现与 --rf 缺省读 cost_of_equity_inputs.csv
  python3 scripts/fetch_equity_bond_inputs.py --refresh
  python3 scripts/fetch_cost_of_equity_inputs.py
}

case "$SCAN_STAGE" in
  evidence)
    : "${SCAN_SINCE:?Set SCAN_SINCE to the previous successful scan date}"
    : "${SCAN_REPORT_DATE:?Set SCAN_REPORT_DATE to the latest reporting period}"
    refresh_market_inputs
    python3 scripts/fetch_a_share_report_disclosures.py --signal-date "$SCAN_DATE" --report-date "$SCAN_REPORT_DATE" --output data/interim/a_share_report_disclosures.csv
    python3 scripts/fetch_a_share_earnings_forecasts.py --signal-date "$SCAN_DATE" --report-date "$SCAN_REPORT_DATE" --output data/interim/a_share_earnings_forecasts.csv
    python3 scripts/fetch_ohlcv_history.py --signal-date "$SCAN_DATE" --actions-only
    python3 scripts/fetch_daily_market_evidence.py --as-of "$SCAN_DATE" --since "$SCAN_SINCE"
    python3 scripts/daily_execution_guard.py evidence --as-of "$SCAN_DATE" --since "$SCAN_SINCE"
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
    python3 scripts/build_a_share_core_valuation_pool.py --md-only --quotes fetch --signal-date "$SCAN_DATE"
    scan_cash_args=()
    if [[ -n "${SCAN_CASH:-}" ]]; then scan_cash_args+=(--cash "$SCAN_CASH"); fi
    if [[ -n "${SCAN_DEBT:-}" ]]; then scan_cash_args+=(--debt "$SCAN_DEBT"); fi
    python3 scripts/screen_daily_volume_price_signals.py --as-of "$SCAN_DATE" "${scan_cash_args[@]}" \
      --review-queue data/interim/a_share_report_update_queue.csv \
      --model-bands data/processed/a_share_pool_model_bands_adopted.csv \
      --hold-bands data/processed/a_share_pool_model_bands_hold.csv \
      --nav "$SCAN_NAV" --funds "$SCAN_FUNDS" --workers 16
    ;;
  preview)
    # 行情预览（§8.2 不给 --nav 只写 daily_quote_preview_<日期>.csv，不发布执行计划）
    refresh_market_inputs
    python3 scripts/screen_daily_volume_price_signals.py --as-of "$SCAN_DATE" --workers 16 \
      --output-csv "data/interim/daily_quote_preview_${SCAN_DATE}.csv"
    ;;
  events)
    # 只重取公告、公司行动与市场背景并重做同日证据凭据（evidence 阶段的子集，用于截止时间后的补取）
    : "${SCAN_SINCE:?Set SCAN_SINCE to the previous successful scan date}"
    python3 scripts/fetch_daily_market_evidence.py --as-of "$SCAN_DATE" --since "$SCAN_SINCE"
    python3 scripts/daily_execution_guard.py evidence --as-of "$SCAN_DATE" --since "$SCAN_SINCE"
    ;;
  *) printf '%s\n' 'SCAN_STAGE must be evidence, preview, events or scan' >&2; exit 2 ;;
esac

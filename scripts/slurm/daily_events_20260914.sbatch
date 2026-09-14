#!/bin/bash
#SBATCH -J rk_events_0914
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 00:15:00
#SBATCH --mem-per-cpu=1792M
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 -u - <<'PY'
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, 'scripts')
from fetch_a_share_dividends import fetch_ex_dividend_events

day = '2026-09-14'
out = Path('data/interim')
codes = set()
for file in ['a_share_core_valuation_pool.csv', 'a_share_holdings.csv']:
    with (Path('data/processed') / file).open() as handle:
        codes.update(r['security_code'].zfill(6) for r in csv.DictReader(handle))

def fetch(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            return urllib.request.urlopen(request, timeout=20).read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)

items, sources = {}, []
total = None
count = 0
for page in range(1, 201):
    params = urllib.parse.urlencode(dict(sr=-1, page_size=100, page_index=page,
        ann_type='A', begin_time='2026-09-11', end_time='2026-09-15'))
    url = 'https://np-anotice-stock.eastmoney.com/api/security/ann?' + params
    data = json.loads(fetch(url)).get('data') or {}
    rows = data.get('list') or []
    if total is None:
        total = int(data.get('total_hits', 0))
        assert total > 0, 'Empty all-market announcement response'
    sources.append(url)
    count += len(rows)
    for row in rows:
        if any(c.get('stock_code', '').zfill(6) in codes for c in row.get('codes', [])):
            items[row['art_code']] = row
    print('Announcement page', page, 'rows', len(rows), 'retrieved', count, 'total', total)
    if count >= total:
        break
    assert rows, 'Announcement pagination ended before total_hits'
else:
    raise RuntimeError('Announcement pagination limit')
snapshot = dict(signal_date=day, query_start='2026-09-11', query_end='2026-09-15',
    retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
    query_scope='Public all-market announcements; portfolio and pool codes filtered locally only',
    queried_all_market_rows=count, reported_total_hits=total,
    locally_filtered_codes=sorted(codes), source_urls=sources,
    announcements=list(items.values()))
(out / f'daily_announcements_{day}.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
events = dict(signal_date=day, retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
    source='eastmoney:RPT_SHAREBONUS_DET, full-market ex-dividend date query',
    events=fetch_ex_dividend_events(day))
(out / f'daily_corporate_actions_{day}.json').write_text(json.dumps(events, ensure_ascii=False, indent=2) + '\n')
url = 'https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,sh000300'
raw = fetch(url).decode('gbk')
indices = []
for symbol, text in re.findall(r'v_([^=]+)="([^"]*)";', raw):
    fields = text.split('~')
    assert fields[30].startswith(day.replace('-', '')), (symbol, fields[30])
    indices.append(dict(code=fields[2], name=fields[1], close=float(fields[3]),
        change_pct=float(fields[32]), amount_cny=float(fields[37]) * 10000,
        quote_time_beijing=fields[30], raw_fields=fields))
market = dict(signal_date=day, source_url=url,
    retrieved_at_utc=datetime.now(timezone.utc).isoformat(), indices=indices,
    shenzhen_shanghai_combined_amount_cny=sum(r['amount_cny'] for r in indices if r['code'] in {'000001', '399001'}),
    coverage_note='沪深成交额不含北交所；全市场涨跌家数另据可核验来源补充，不以关注池替代。')
(out / f'daily_market_context_{day}.json').write_text(json.dumps(market, ensure_ascii=False, indent=2) + '\n')
print('Saved', len(items), 'pool announcements;', len(events['events']), 'corporate actions;', len(indices), 'indices')
PY

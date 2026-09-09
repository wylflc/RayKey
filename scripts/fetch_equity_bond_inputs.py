#!/usr/bin/env python3
"""Fetch public CSI300 aggregate TTM PE and CN10Y; save observations, never sessions."""
import argparse
from bisect import bisect_right
import csv
from datetime import datetime
import hashlib
import http.cookiejar
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo
from fetch_cost_of_equity_inputs import fetch_treasury_yields

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/macro'


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def fetch_pe():
    page_url = 'https://legulegu.com/stockdata/hs300-ttm-lyr'
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': page_url}
    page = opener.open(urllib.request.Request(page_url, headers=headers), timeout=30).read().decode()
    match = re.search(r'<meta[^>]+name="_csrf"[^>]+content="([^"]+)"', page)
    if not match: raise RuntimeError('Public valuation session unavailable')
    headers['X-CSRF-Token'] = match.group(1)
    params = urllib.parse.urlencode({'token': hashlib.md5(datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat().encode()).hexdigest(),
                                    'indexCode': '000300.SH'})
    request = urllib.request.Request('https://legulegu.com/api/stockdata/index-basic-pe?' + params, headers=headers)
    data = json.load(opener.open(request, timeout=30)).get('data', [])
    if not data: raise RuntimeError('Empty valuation source')
    rows = []
    for row in data:
        day = (datetime.fromtimestamp(float(row['date']) / 1000, ZoneInfo('Asia/Shanghai')).date().isoformat()
               if isinstance(row['date'], (int, float)) else row['date'][:10])
        rows.append({'observed_on': day, 'pe_ttm': row['addTtmPe'], 'index_close': row['close'], 'source': page_url})
    return sorted(rows, key=lambda r: r['observed_on'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/reference/equity_bond_csi300.csv')
    args = parser.parse_args()
    if args.refresh:
        write(RAW / 'csi300_pe_ttm.csv', fetch_pe())
        write(RAW / 'china_10y_yield_daily.csv', [{'observed_on': d, 'bond_yield': y,
              'source': 'eastmoney RPTA_WEB_TREASURYYIELD EMM00166466'} for d, y in fetch_treasury_yields(30, .1)])
    with (RAW / 'csi300_pe_ttm.csv').open() as f: pe = list(csv.DictReader(f))
    with (RAW / 'china_10y_yield_daily.csv').open() as f: bonds = sorted(csv.DictReader(f), key=lambda r:r['observed_on'])
    days = [r['observed_on'] for r in bonds]
    joined = []
    for r in sorted(pe, key=lambda r:r['observed_on']):
        i = bisect_right(days, r['observed_on']) - 1
        if i < 0: raise ValueError('No past bond observation')
        joined.append({'observed_on': r['observed_on'], 'index_code': '000300', 'pe_ttm': r['pe_ttm'],
                       'bond_yield': bonds[i]['bond_yield'], 'bond_observed_on': days[i],
                       'pe_source': r['source'], 'bond_source': bonds[i]['source']})
    write(args.output, joined)
    from equity_bond_constraint import EquityBondConstraint
    signal = EquityBondConstraint(args.output)
    print(f'{len(joined)} observations: {signal.days[0]} to {signal.days[-1]}')


if __name__ == '__main__': main()

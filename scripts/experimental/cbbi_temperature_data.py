#!/usr/bin/env python3
"""Fetch and freeze the seven-asset temperature study inputs; production is untouched."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from corporate_actions import ACTION_FIELDS, correct_components, unique_actions
from fetch_ohlcv_history import fetch_actions, fetch_rights, secid
from fetch_a_share_share_changes import fetch_one, FIELDS as SHARE_FIELDS

EXP = ROOT / 'data/experiments/exp_cbbi_temperature_20260922'
QUOTE_FIELDS = ['date', 'open', 'close', 'high', 'low', 'volume', 'turnover_pct', 'amount_10k_cny']


def read_csv(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not fields:
        fields = list(rows[0])
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n', extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def get_json(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read()
            return json.loads(raw), hashlib.sha256(raw).hexdigest()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def quotes(code, cutoff, manifest):
    sid = 'sh000300' if code == '000300' else secid(code, '')
    until = date.fromisoformat(cutoff)
    found = {}
    for page in range(24):
        url = ('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?'
               + urllib.parse.urlencode({'param': f'{sid},day,,{until.isoformat()},640,'}))
        payload, digest = get_json(url)
        data = payload.get('data') or {}
        bars = (data.get(sid) or {}).get('day', []) if isinstance(data, dict) else []
        bars = [r for r in bars if r[0] <= until.isoformat()]
        manifest.append(dict(kind='quote_page', code=code, url=url, sha256=digest, rows=len(bars)))
        if not bars:
            break
        for r in bars:
            found.setdefault(r[0], dict(zip(QUOTE_FIELDS, [*r[:6], r[7] if len(r) > 7 else '',
                                                                    r[8] if len(r) > 8 else ''])))
        oldest = min(r[0] for r in bars)
        print('quotes', code, page, len(bars), oldest, max(r[0] for r in bars), flush=True)
        new_until = date.fromisoformat(oldest) - timedelta(days=1)
        if new_until >= until:
            raise ValueError('Quote pagination did not progress')
        until = new_until
        time.sleep(.15)
    else:
        raise ValueError('Quote pagination exceeded maximum pages')
    if not found:
        raise ValueError(f'No quotes: {code}')
    rows = [found[d] for d in sorted(found)]
    source_path = ROOT / 'data/raw/ohlcv' / ('INDEX_000300.csv' if code == '000300' else f'{code}.csv')
    cache = {r['date']: r for r in read_csv(source_path)}
    mismatches = []
    for r in rows:
        old = cache.get(r['date'])
        if old and abs(float(old['close']) - float(r['close'])) > .011:
            mismatches.append({'code': code, 'date': r['date'], 'cached': old['close'], 'fresh': r['close']})
    write_csv(EXP / 'inputs/quotes' / f'{code}.csv', rows, QUOTE_FIELDS)
    return mismatches


def main():
    global EXP
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=EXP)
    args = ap.parse_args()
    EXP = args.out
    config = json.loads((EXP / 'config.json').read_text())
    codes = list(config['assets'])
    stock_codes = set(codes) - {'000300'}
    inp = EXP / 'inputs'
    inp.mkdir(parents=True, exist_ok=True)
    manifest, failures, quote_differences = [], [], []
    for code in codes:
        path = inp / 'quotes' / f'{code}.csv'
        if path.exists():
            print('reuse frozen quotes', code, flush=True)
            continue
        quote_differences.extend(quotes(code, config['as_of'], manifest))
    if quote_differences:
        write_csv(inp / 'quote_cache_differences.csv', quote_differences)

    for code in ['H00300', '000300']:
        p = inp / f'csi_{code}.json'
        if p.exists():
            continue
        url = ('https://www.csindex.com.cn/csindex-home/perf/index-perf?'
               + urllib.parse.urlencode({'indexCode': code, 'startDate': '20050101',
                                         'endDate': config['as_of'].replace('-', '')}))
        payload, digest = get_json(url)
        if not isinstance(payload.get('data'), list) or len(payload['data']) < 4000:
            raise ValueError('Incomplete official CSI history')
        p.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
        manifest.append(dict(kind='official_index', code=code, url=url, sha256=digest,
                             rows=len(payload['data'])))
        print('CSI', code, len(payload['data']), flush=True)

    old = [r for r in read_csv(ROOT / 'data/raw/corporate_actions/a_share_corporate_actions.csv')
           if r['security_code'] in stock_codes]
    all_actions = []
    for code in sorted(stock_codes):
        fresh = fetch_actions(code, 20)
        if not fresh:
            raise ValueError(f'Empty fresh distributions: {code}')
        try:
            rights = fetch_rights(code, 15)
        except Exception as exc:
            rights = []
            failures.append(dict(kind='rights_refresh', code=code, error=type(exc).__name__,
                                 fallback='existing verified repository rights rows'))
        by_key = {(r['ex_dividend_date'], r['rights_ratio'], r['rights_price']): r
                  for r in old if r['security_code'] == code and float(r.get('rights_ratio') or 0)}
        by_key.update({(r['ex_dividend_date'], r['rights_ratio'], r['rights_price']): r for r in rights})
        all_actions.extend(fresh + list(by_key.values()))
        print('actions', code, len(fresh), 'rights', len(by_key), flush=True)
    write_csv(inp / 'actions.csv', correct_components(unique_actions(all_actions)), ACTION_FIELDS)

    old_shares = read_csv(ROOT / 'data/raw/share_changes/a_share_share_changes.csv')
    share_rows = []
    for code in sorted(stock_codes):
        data, error = fetch_one(code, 20)
        if error or not data:
            failures.append(dict(kind='shares_refresh', code=code, error=error or 'empty',
                                 fallback='repository history'))
            share_rows.extend(r for r in old_shares if r['security_code'] == code)
            continue
        for r in data:
            share_rows.append(dict(security_code=code, security_name=config['assets'][code],
                effective_date=str(r['END_DATE'])[:10], change_reason=r.get('CHANGE_REASON'),
                total_shares=r.get('TOTAL_SHARES'), limited_shares=r.get('LIMITED_SHARES'),
                unlimited_shares=r.get('UNLIMITED_SHARES'), source='eastmoney:RPT_F10_EH_EQUITY',
                retrieved_at_utc=datetime.now(timezone.utc).isoformat()))
    write_csv(inp / 'shares.csv', sorted(share_rows, key=lambda r:(r['security_code'], r['effective_date'])), SHARE_FIELDS)

    financials = []
    for p in sorted((ROOT / 'data/raw/financials').glob('????-??-??.csv')):
        with p.open(newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if row['security_code'] in stock_codes:
                    financials.append(row)
    write_csv(inp / 'financials.csv', financials)
    for source, target in [('data/reference/equity_bond_csi300.csv', 'equity_bond_csi300.csv'),
                           ('data/raw/macro/china_10y_yield_daily.csv', 'bond_yields.csv'),
                           ('data/reference/a_share_exright_terms.csv', 'price_terms.csv'),
                           ('data/reference/a_share_action_component_corrections.csv', 'action_corrections.csv')]:
        p = ROOT / source
        rows = read_csv(p)
        if rows and 'security_code' in rows[0]:
            rows = [r for r in rows if r['security_code'] in stock_codes]
        write_csv(inp / target, rows)
        manifest.append(dict(kind='local_snapshot', path=source, sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    files = {str(p.relative_to(EXP)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(inp.rglob('*')) if p.is_file()}
    (EXP / 'input_manifest.json').write_text(json.dumps(dict(
        fetched_at_utc=datetime.now(timezone.utc).isoformat(), cutoff=config['as_of'],
        sources=manifest, limitations=failures, sha256=files), ensure_ascii=False, indent=2) + '\n')
    print('Frozen', len(files), 'files; financials', len(financials), 'limitations', failures, flush=True)


if __name__ == '__main__':
    main()

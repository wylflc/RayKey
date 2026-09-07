#!/usr/bin/env python3
"""Complete the frozen OI-150 study; preserve missing observations and audit PIT inputs.

Execution decisions are recorded in exp_oi150_overseas_forward/execution_20260907.md.
This runner does not write production prices, states, valuation bands or portfolios.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta, datetime, timezone
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'scripts/experimental')]
import overseas_pv_forward as old
import fetch_us_ohlcv_history as us

EXP, RAW = old.EXP, old.RAW
US_EXP = ROOT / 'data/experiments/exp_us_sp500_port'
PRICE_DIR = RAW / 'prices_by_cik'
END = '2026-09-04'
GROUPS = list(range(2010, 2021))


def csv_rows(p):
    return old.read_csv(Path(p))


def save_csv(p, rows, fields=None):
    old.write_csv(Path(p), rows, fields or list(rows[0]))


def dump(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def observations():
    obs = defaultdict(set)
    for r in csv_rows(EXP / 'universe.csv'):
        obs[r['cik']].update(t for t in old.month_end_dates(r['obs_from'], r['obs_to'])
                             if old.OBS_FROM <= t <= old.OBS_TO)
    return {c: sorted(ds) for c, ds in obs.items()}


def source_series(path, provider):
    if provider == 'tencent':
        return csv_rows(path), [], []
    d = json.loads(Path(path).read_text())
    if provider == 'yahoo':
        res = (d.get('chart') or {}).get('result') or []
        if not res or res[0].get('meta', {}).get('currency') != 'USD':
            return [], [], []
        return us.yahoo_series(d)
    return us.tiingo_series(d) if isinstance(d, list) else ([], [], [])


def prepare(fetch=False):
    """Resolve by CIK, select full source histories without consulting return values."""
    info = csv_rows(EXP / 'universe_ciks.csv')
    obs = observations()
    index = {r['cik']: r for r in csv_rows(ROOT / 'data/raw/ohlcv_us/price_index.csv')}
    ticker_owners = defaultdict(set)
    for r in info:
        if r['ticker']:
            ticker_owners[r['ticker']].add(r['cik'])
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for i, r in enumerate(info, 1):
        cik, ticker = r['cik'], r['ticker']
        candidates, attempts = [], []
        # The US production CSVs clip at index exit; read their original providers instead.
        for key in index.get(cik, {}).get('series', '').split('|'):
            if not key:
                continue
            provider, symbol = key.split(':', 1)
            path = US_EXP / 'raw/prices' / provider / f'{us.ysym(symbol)}.json'
            if path.exists():
                candidates.append((path, provider, 'existing_cik_mapping'))
        unique = bool(ticker and len(ticker_owners[ticker]) == 1)
        if unique:
            path = old.price_path(ticker)
            if path.exists():
                candidates.append((path, 'tencent', r['ticker_source']))
            for provider in ('yahoo', 'tiingo'):
                path = US_EXP / 'raw/prices' / provider / f'{us.ysym(ticker)}.json'
                if path.exists():
                    candidates.append((path, provider, r['ticker_source']))
            for provider, suffix, symbol in (('yahoo', 'json', us.ysym(ticker)), ('tencent', 'csv', ticker)):
                path = RAW / 'market' / provider / f'{symbol}.{suffix}'
                if path.exists():
                    candidates.append((path, provider, r['ticker_source']))
        # A cached 404 response does not count as a usable price source.
        candidates = [x for x in candidates if source_series(x[0], x[1])[0]]
        sub_path = RAW / 'submissions' / f'CIK{cik}.json'
        sub = json.loads(sub_path.read_text()) if sub_path.exists() else {}
        # Only fetch a current Yahoo symbol when SEC maps this issuer to that symbol.
        current = unique and ticker in (sub.get('tickers') or [])
        if fetch and not candidates and current:
            symbol = us.ysym(ticker)
            path = RAW / 'market/yahoo' / f'{symbol}.json'
            if not path.exists():
                url = (f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}'
                       f'?period1=0&period2=1788566400&interval=1d&events=div%2Csplits')
                for attempt in range(2):
                    code, body = us._get(url, timeout=25)
                    attempts.append(f'yahoo:{code}')
                    if code == 200:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(body)
                        break
                    if code in (404, 429):
                        break
                    time.sleep(3)
                time.sleep(0.7)
            if path.exists():
                candidates.append((path, 'yahoo', 'SEC_current_ticker'))
        if fetch and not candidates and unique:
            path = RAW / 'market/tencent' / f'{ticker}.csv'
            if not path.exists():
                for symbol in old.symbol_candidates(ticker, r['exchange']):
                    bars = {}
                    end = END
                    try:
                        while True:
                            got = old.tencent_bars(symbol, old.PRICE_FROM, end)
                            if not got:
                                break
                            bars.update(got)
                            if len(got) < old.TX_MAX_BARS:
                                break
                            end = (date.fromisoformat(min(d for d, _ in got)) - timedelta(days=1)).isoformat()
                            time.sleep(0.7)
                        attempts.append(f'tencent:{symbol}:{len(bars)}')
                        if bars:
                            save_csv(path, [dict(date=d, close=c) for d, c in sorted(bars.items())])
                            break
                    except old.TencentError:
                        attempts.append(f'tencent:{symbol}:unavailable')
                        break  # An unavailable endpoint is not a reason to hammer its aliases.
            if path.exists():
                candidates.append((path, 'tencent', r['ticker_source']))
        best = None
        for path, provider, identity in candidates:
            bars, dividends, splits = source_series(path, provider)
            # Keep source histories intact, while freezing the study's common endpoint.
            clean = {b['date']: float(b['close']) for b in bars
                     if b['date'] <= END and math.isfinite(float(b['close'])) and float(b['close']) > 0}
            if not clean:
                continue
            ds = sorted(clean)
            score = (sum(ds[0] <= t <= ds[-1] for t in obs[cik]),
                     min(ds[-1], END), len(ds))
            if best is None or score > best[0]:
                best = (score, path, provider, identity, clean, dividends, splits)
        forms = (sub.get('filings') or {}).get('recent') or {}
        term = sorted(d for f, d in zip(forms.get('form', []), forms.get('filingDate', []))
                      if f in ('25', '25-NSE', '15-12B', '15-12G', '15-15D'))
        rec = dict(cik=cik, ticker=ticker, status='', source='', provider='', identity='',
                   first='', last='', bars=0, sha256='', terminal_evidence='|'.join(term),
                   attempts='|'.join(attempts))
        if best:
            _, path, provider, identity, clean, dividends, splits = best
            ds = sorted(clean)
            save_csv(PRICE_DIR / f'{cik}.csv', [dict(date=d, close=f'{clean[d]:.4f}') for d in ds])
            dump(PRICE_DIR / f'{cik}_actions.json', dict(dividends=dividends, splits=splits))
            rec.update(status='ok', source=str(path.relative_to(ROOT)), provider=provider, identity=identity,
                       first=ds[0], last=ds[-1], bars=len(ds), sha256=digest(path))
        else:
            rec['status'] = 'no_ticker' if not ticker else ('ambiguous_ticker' if not unique else 'no_price')
        records.append(rec)
        if i % 25 == 0:
            print(f'prices {i}/{len(info)} {dict(Counter(x["status"] for x in records))}', flush=True)
            save_csv(EXP / 'price_sources.csv', records)
    save_csv(EXP / 'price_sources.csv', records)
    print('prices complete', dict(Counter(x['status'] for x in records)), flush=True)


def frame_audit(cik, facts):
    """Link the exact frame accession to its filing date; do not repair the frozen sample."""
    by_accn = defaultdict(set)
    for tax in facts.values():
        for node in tax.values():
            for es in (node.get('units') or {}).values():
                for e in es:
                    if e.get('accn') and e.get('filed'):
                        by_accn[e['accn']].add(e['filed'])
    result = []
    for r in csv_rows(EXP / 'universe.csv'):
        if r['cik'] != cik:
            continue
        hits = []
        for concept in old.REV_CONCEPTS:
            path = RAW / 'frames' / f'{concept}_CY{r["cy"]}.json'
            if not path.exists():
                continue
            for e in json.loads(path.read_text()).get('data', []):
                if str(e['cik']).zfill(10) == cik and float(e['val']) == float(r['revenue']):
                    fs = sorted(by_accn.get(e.get('accn', ''), []))
                    # Later accessions can repeat a value already public at entry.
                    equivalent = sorted(x['filed'] for x in facts.get('us-gaap', {}).get(concept, {}).get('units', {}).get('USD', [])
                                        if x.get('filed') and x.get('start') == e.get('start')
                                        and x.get('end') == e.get('end') and float(x.get('val', -1)) == float(e['val']))
                    first = equivalent[0] if equivalent else (fs[0] if fs else '')
                    hits.append((first, concept, e.get('accn', ''), e.get('start', ''), e.get('end', ''), fs[0] if fs else ''))
        known = [x for x in hits if x[0]]
        hit = min(known) if known else (hits[0] if hits else ('', '', '', '', '', ''))
        filed, concept, accn, start, end, source_filed = hit
        result.append(dict(cik=cik, cy=r['cy'], obs_from=r['obs_from'], concept=concept,
                           accession=accn, filed=filed, source_filed=source_filed, period_start=start, period_end=end,
                           status=('available' if filed <= r['obs_from'] else 'filed_after_entry') if filed else 'unknown'))
    return result


def filtered_facts(facts, t):
    # PitFacts is also imported by OI-159; do not alter its behavior for that experiment.
    return {tax: {c: {'units': {u: [e for e in es if e.get('filed') and e['filed'] <= t]
                                for u, es in node.get('units', {}).items()}}
                  for c, node in concepts.items()}
            for tax, concepts in facts.items() if tax in ('us-gaap', 'ifrs-full', 'dei')}


def rank_correlation(pairs):
    if len(pairs) < 2:
        return None
    def ranks(xs):
        order = sorted(range(len(xs)), key=xs.__getitem__)
        out = [0.] * len(xs)
        i = 0
        while i < len(xs):
            j = i + 1
            while j < len(xs) and xs[order[j]] == xs[order[i]]:
                j += 1
            for k in range(i, j):
                out[order[k]] = (i + j - 1) / 2
            i = j
        return out
    a, b = ranks([p for p, _ in pairs]), ranks([v for _, v in pairs])
    ma, mb = statistics.mean(a), statistics.mean(b)
    den = math.sqrt(sum((x-ma)**2 for x in a) * sum((y-mb)**2 for y in b))
    return sum((x-ma)*(y-mb) for x, y in zip(a, b)) / den if den else None


def forward(tr, days, start, years, terminal_evidence):
    if not days or start not in tr:
        return None, 'no_start'
    target = date.fromisoformat(start)
    try:
        target = target.replace(year=target.year + years)
    except ValueError:
        target = target.replace(year=target.year + years, day=28)
    if target.isoformat() > END:
        return None, 'window_incomplete'
    pos = bisect.bisect_right(days, target.isoformat()) - 1
    if pos < 0:
        return None, 'no_end'
    end = days[pos]
    if end > start and (target - date.fromisoformat(end)).days <= 10:
        return (tr[end] / tr[start]) ** (1 / years) - 1, 'full'
    # A gap inside a longer series is not delisting, nor is index removal.
    if days[-1] < target.isoformat() and days[-1] >= start:
        last = date.fromisoformat(days[-1])
        if any(abs((date.fromisoformat(d) - last).days) <= 120 for d in terminal_evidence):
            return (tr[days[-1]] / tr[start]) ** (1 / years) - 1, 'delisted_terminal'
    return None, 'unverified_terminal_or_gap'


def run_worker(job):
    r, obs, source, rf = job
    cik, ticker = r['cik'], r['ticker']
    facts_path = old.facts_path(cik)
    payload = json.loads(facts_path.read_text())
    assert str(payload['cik']).zfill(10) == cik, 'SEC cache issuer mismatch'
    facts = payload.get('facts', {})
    frame = frame_audit(cik, facts)
    prices_path = PRICE_DIR / f'{cik}.csv'
    prices = [(x['date'], float(x['close'])) for x in csv_rows(prices_path)] if source['status'] == 'ok' else []
    days = [d for d, _ in prices]
    sec_splits = old.split_events(facts)
    inferred = old.inferred_splits(prices, old.shares_series(facts), sec_splits, ratios=(2,3,4,5,7,10,20))
    splits = sorted(set(sec_splits) | set(inferred))
    divs = old.dividend_events(facts)
    actions_path = PRICE_DIR / f'{cik}_actions.json'
    src_actions = json.loads(actions_path.read_text()) if source['status'] == 'ok' and actions_path.exists() else {'splits': [], 'dividends': []}
    provider_splits = src_actions['splits']
    # SEC context end is not always the effective split date. Require a matching price jump or provider event.
    dubious = []
    for d, ratio in sec_splits:
        i = bisect.bisect_left(days, d)
        jump = bool(0 < i < len(prices) and abs(prices[i-1][1] / prices[i][1] / ratio - 1) <= .15)
        matched = any(abs((date.fromisoformat(sd) - date.fromisoformat(d)).days) <= 3 and abs(k / ratio - 1) < .001
                      for sd, k in provider_splits)
        if days and days[0] <= d <= days[-1] and not (jump or matched):
            dubious.append((d, ratio))
    missing_splits = [(d, k) for d, k in provider_splits if days and days[0] <= d <= days[-1]
                      and not any(abs((date.fromisoformat(sd) - date.fromisoformat(d)).days) <= 3
                                  and abs(sk/k-1) < .001 for sd, sk in splits)]
    tr = old.total_return_series(prices, splits, divs)
    action_audit = dict(cik=cik, sec_splits=len(sec_splits), inferred_splits=len(inferred),
                        sec_dividends=len(divs), provider_splits=len(provider_splits),
                        split_conflicts=len(dubious), split_missing=len(missing_splits),
                        no_actions=int(not splits and not divs),
                        conflict_detail=json.dumps(dubious), missing_detail=json.dumps(missing_splits))
    out = []
    for t in obs:
        rec = dict(cik=cik, ticker=ticker, date=t, status='', reason='', price='', price_date='',
                   value='', pv='', period='', rf='', max_filed='', report_currency='',
                   fwd3='', kind3='', fwd5='', kind5='', action_warning='')
        i = bisect.bisect_right(days, t) - 1
        if i >= 0 and (date.fromisoformat(t) - date.fromisoformat(days[i])).days <= 7:
            rec['price'], rec['price_date'] = f'{prices[i][1]:.4f}', days[i]
        clipped = filtered_facts(facts, t)
        filed = [e['filed'] for tax in clipped.values() for node in tax.values()
                 for es in node['units'].values() for e in es]
        rec['max_filed'] = max(filed, default='')
        assert not rec['max_filed'] or rec['max_filed'] <= t
        annuals = old.fos.sec_extract(cik, r['name'], {'facts': clipped})
        rf_t = old.rf_at(*rf, t)
        rec['rf'] = f'{rf_t:.6f}' if rf_t is not None else ''
        if not annuals:
            rec.update(status='no_annual', reason='no filed<=t annual statements')
        elif rf_t is None:
            rec.update(status='no_rf')
        else:
            pit = old.PitFacts(clipped)
            tax = clipped.get(pit.tax_name, {})
            maps = old.fos.IFRS if pit.tax_name == 'ifrs-full' else old.fos.GAAP
            current = old.fos.sec_current_extract(cik, r['name'], tax, maps, annuals, dei=clipped.get('dei'))
            latest = current if current and current['period'] > annuals[-1]['period'] else annuals[-1]
            rec['period'], rec['report_currency'] = latest['period'], latest['report_currency']
            if latest['report_currency'] != 'USD':
                rec.update(status='currency_unverified', reason='historical FX/ADR basis not provided by preregistration')
            elif pit.tax_name == 'ifrs-full' or ticker in ('TSM', 'ASML', 'PDD'):
                rec.update(status='share_basis_unverified', reason='ADR/ordinary-share historical ratio unverified')
            else:
                years = [old.bor.year_from_row(x) for x in annuals]
                cur = old.bor.year_from_row(current) if current else None
                try:
                    val = old.bor.value_company(cik, 'L2', years, {'rf_usd': rf_t, 'erp_us': old.ERP_US}, cur)
                except Exception as exc:
                    rec.update(status='error', reason=f'{type(exc).__name__}: {str(exc)[:100]}')
                else:
                    if val.get('status') != 'ok':
                        rec.update(status='rejected', reason=val.get('reason', ''))
                    else:
                        factor = math.prod(k for d, k in splits if latest['period'] < d <= t)
                        value = float(val['value']) / factor
                        if value <= 0 or not math.isfinite(value):
                            rec.update(status='invalid_value')
                        else:
                            rec['value'] = f'{value:.8f}'
                            if rec['price']:
                                rec.update(status='ok', pv=f'{float(rec["price"])/value:.8f}')
                            else:
                                rec.update(status=source['status'] if source['status'] != 'ok' else 'no_price_at_observation')
        if rec['status'] == 'ok':
            for h in (3, 5):
                value, kind = forward(tr, days, rec['price_date'], h, source['terminal_evidence'].split('|') if source['terminal_evidence'] else [])
                rec[f'fwd{h}'] = f'{value:.10f}' if value is not None else ''
                rec[f'kind{h}'] = kind
            if dubious or missing_splits:
                rec['action_warning'] = 'split_date_or_coverage_unverified'
        out.append(rec)
    return out, frame, action_audit


def value(workers):
    info = csv_rows(EXP / 'universe_ciks.csv')
    obs = observations()
    sources = {r['cik']: r for r in csv_rows(EXP / 'price_sources.csv')}
    rates = csv_rows(ROOT / 'data/reference/cost_of_equity_inputs_us.csv')
    rates.sort(key=lambda r: r['observed_on'])
    rf = ([r['observed_on'] for r in rates], [float(r['risk_free_rate']) for r in rates])
    paths = [EXP / 'universe.csv', EXP / 'universe_ciks.csv', EXP / 'execution_20260907.md',
             EXP / 'price_sources.csv', Path(__file__), Path(old.__file__), Path(old.fos.__file__), Path(old.bor.__file__),
             ROOT / 'data/reference/cost_of_equity_inputs_us.csv']
    paths += [old.facts_path(r['cik']) for r in info]
    paths += sorted((RAW / 'frames').glob('*.json'))
    paths += sorted(PRICE_DIR.glob('*'))
    paths += [Path(us.__file__), ROOT/'scripts/roic_inputs.py', ROOT/'scripts/intrinsic_value.py',
              ROOT/'scripts/experimental/moat_param_lab.py']
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                    inputs={str(p.relative_to(ROOT)): digest(p) for p in paths},
                    expected_companies=len(info), expected_months=sum(map(len, obs.values())),
                    observation_from=old.OBS_FROM, observation_to=old.OBS_TO, data_end=END)
    dump(EXP / 'manifest.json', manifest)
    jobs = [(r, obs[r['cik']], sources[r['cik']], rf) for r in info]
    frames, actions, n = [], [], 0
    with (EXP / 'pv_monthly.csv').open('w', newline='') as f:
        writer = None
        with Pool(workers) as pool:
            for i, (rows, fs, ac) in enumerate(pool.imap(run_worker, jobs), 1):
                if writer is None:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
                    writer.writeheader()
                writer.writerows(rows); f.flush()
                n += len(rows); frames.extend(fs); actions.append(ac)
                if i % 25 == 0:
                    print(f'value {i}/{len(info)}, observations {n}', flush=True)
    assert n == manifest['expected_months']
    save_csv(EXP / 'universe_pit_audit.csv', sorted(frames, key=lambda x: (x['cy'], x['cik'])))
    save_csv(EXP / 'corporate_action_audit.csv', sorted(actions, key=lambda x: x['cik']))
    print(f'value complete: {n} observations', flush=True)


def missing_bounds(known_total, known_missing, unclassified):
    """Unclassified P/V observations cannot be assigned to a bin: report identified bounds."""
    lower = known_missing / known_total if known_total else None
    upper = (known_missing + unclassified) / (known_total + unclassified) if known_total + unclassified else None
    return lower, upper


def report():
    manifest = json.loads((EXP / 'manifest.json').read_text())
    for p, h in manifest['inputs'].items():
        assert digest(ROOT/p) == h, f'input changed since valuation: {p}'
    rows = csv_rows(EXP / 'pv_monthly.csv')
    expected = {(c, t) for c, ds in observations().items() for t in ds}
    actual = [(r['cik'], r['date']) for r in rows]
    assert len(set(actual)) == len(actual) and set(actual) == expected, 'missing/duplicate company-month'
    assert all(not r['max_filed'] or r['max_filed'] <= r['date'] for r in rows)
    frames = csv_rows(EXP / 'universe_pit_audit.csv')
    actions = csv_rows(EXP / 'corporate_action_audit.csv')
    sources = csv_rows(EXP / 'price_sources.csv')
    n = len(rows)
    classified = [r for r in rows if r['pv'] and old.bucket_of(float(r['pv'])) != 'NA']
    unclassified = n - len(classified)
    statuses = dict(Counter(r['status'] for r in rows))
    # The preregistered 15% gate specifically concerns absent security/price data.
    # Keep model rejection and forward-window attrition separately visible.
    market_missing = sum(not r['price'] for r in rows)
    pit_status = dict(Counter(r['status'] for r in frames))
    issues = []
    if market_missing/n > .15:
        issues.append('原方案无证券映射/无观测价格的公司月并集超过15%')
    if pit_status.get('filed_after_entry') or pit_status.get('unknown'):
        issues.append('原股票池的营收 frame 不能全部确认在入池前可得')
    horizons = {}
    for h in (3, 5):
        usable = [r for r in classified if r[f'fwd{h}']]
        missing = n-len(usable)
        groups, buckets = [], []
        for g in GROUPS:
            selected = [r for r in usable if old.year_group(r['date']) == g]
            pairs = [(float(r['pv']), float(r[f'fwd{h}'])) for r in selected]
            groups.append(dict(year=g, n=len(pairs), rho=rank_correlation(pairs)))
        for lo, hi in old.BUCKETS:
            all_bin = [r for r in classified if lo <= float(r['pv']) < hi]
            have = [r for r in all_bin if r[f'fwd{h}']]
            vals = [float(r[f'fwd{h}']) for r in have]
            lower, upper = missing_bounds(len(all_bin), len(all_bin)-len(have), unclassified)
            buckets.append(dict(bucket=f'[{lo:g},{hi:g})', n=len(have), companies=len({r['cik'] for r in have}),
                                median=statistics.median(vals) if vals else None,
                                known_missing=len(all_bin)-len(have), missing_lower=lower, missing_upper=upper))
        a, b = buckets[1]['median'], buckets[3]['median']
        gap = (a-b)*100 if a is not None and b is not None else None
        negative = sum(g['rho'] is not None and g['rho'] < 0 for g in groups)
        group_complete = all(g['rho'] is not None for g in groups)
        passes = group_complete and negative >= math.ceil(2*len(GROUPS)/3) and gap is not None and gap >= 3
        if any(b['missing_upper'] is None or b['missing_upper'] > .20 for b in buckets):
            issues.append(f'{h}年各档缺失率不能全部确认不超过20%')
        if not group_complete or gap is None:
            issues.append(f'{h}年比较档/观测年组不完整')
        horizons[str(h)] = dict(n=len(usable), excluded=missing, excluded_share=missing/n,
                               rho=rank_correlation([(float(r['pv']), float(r[f'fwd{h}'])) for r in usable]),
                               negative_groups=negative, total_groups=len(GROUPS), gap_pp=gap,
                               descriptive_criteria_pass=passes, groups=groups, buckets=buckets,
                               terminal_count=sum(r[f'kind{h}']=='delisted_terminal' for r in usable),
                               action_warning_count=sum(bool(r['action_warning']) for r in usable))
    if any(int(r['split_conflicts']) or int(r['split_missing']) for r in actions):
        issues.append('SEC拆股事实与原始价格/公司行动存在日期或覆盖差异')
    outcome = '不可判' if issues else ('支持 H1' if all(v['descriptive_criteria_pass'] for v in horizons.values()) else '不支持 H1')
    result = dict(outcome=outcome, reasons=issues, company_months=n, companies=len({r['cik'] for r in rows}),
                  status=statuses, universe_pit=pit_status, unknown_bucket=unclassified,
                  prereg_market_missing=market_missing, prereg_market_missing_share=market_missing/n,
                  price_status=dict(Counter(r['status'] for r in sources)), horizons=horizons,
                  integrity=dict(exact_original_observations=True, duplicate_observations=0, future_filed=0,
                                 inputs_match_manifest=True),
                  artifacts={f:digest(EXP/f) for f in ('pv_monthly.csv','universe_pit_audit.csv','corporate_action_audit.csv','price_sources.csv')})
    dump(EXP / 'result.json', result)
    fmt = lambda v, digits=3: '—' if v is None else f'{v:+.{digits}f}'
    lines = ['# OI-150 原预登记检验执行结果', '', f'**正式结论：{outcome}。**', '',
             '原样本、分档、观测期和收益门槛保留。下列收益读数受数据前提限制，不能作为通过或否定原假设的正式证据。', '',
             f'全量展开 {n:,} 个公司月、{result["companies"]} 家；与原股票池逐项核对，缺行、重复行和估值使用未来申报均为零。', '',
             '## 数据前提与缺失', '', '最终结论的原因：', '']
    lines += [f'- {s}。' for s in issues]
    lines += ['', '公司月状态（所有原样本均在分母内）：', '', '| 状态 | 公司月 | 占比 |', '| --- | ---: | ---: |']
    lines += [f'| {s} | {v} | {v/n:.2%} |' for s,v in sorted(statuses.items(), key=lambda p:-p[1])]
    lines += ['', f'原股票池 4,400 条公司年营收记录的来源申报审计：{pit_status}。原始 frames 的 accession 逐条连接 SEC filed 日期；同时查同概念、期间和金额的更早申报，已公开的相同值不误判为未来信息。原股票池不改。',
              '', f'原方案无证券映射/无观测价格并集 {market_missing:,}/{n:,}（{market_missing/n:.2%}；15%门槛）。模型拒绝等未重复加到这一并集中。',
              '下表总缺失率另列所有无法估值/定价/换算或无完整前向收益的公司月比例，不冒充原15%价格门槛。',
              f'不能分配到原八档的公司月 {unclassified:,} 条；各档报告缺失率上下界，不能将未知所属档当作零缺失。',
              '该完整性口径同时报告全部状态，便于区分原方案特别关注的无代码/无价格与模型自身拒绝。', '',
              '## 描述性收益读数', '', '| 期限 | 有收益公司月 | 总缺失率 | 负相关年组 | 合并Spearman | 便宜档−比较档 pp/年 | 两项数值判据 |',
              '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for h, v in horizons.items():
        lines.append(f'| {h}年 | {v["n"]} | {v["excluded_share"]:.2%} | {v["negative_groups"]}/11 | {fmt(v["rho"])} | {fmt(v["gap_pp"],2)} | {"达到" if v["descriptive_criteria_pass"] else "未达到"} |')
    for h,v in horizons.items():
        lines += ['', f'### {h}年分档', '', '| P/V档 | 观测 | 公司 | 年化中位 | 缺失率下界 | 缺失率上界 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
        for b in v['buckets']:
            pct=lambda x:'—' if x is None else f'{x:.2%}'
            lines.append(f'| {b["bucket"]} | {b["n"]} | {b["companies"]} | {pct(b["median"])} | {pct(b["missing_lower"])} | {pct(b["missing_upper"])} |')
        lines += ['', f'### {h}年逐观测年组', '', '| 4月末起观测年 | 公司月 | Spearman |', '| --- | ---: | ---: |']
        lines += [f'| {g["year"]} | {g["n"]} | {fmt(g["rho"])} |' for g in v['groups']]
        lines += ['', f'有证券终止申报支持的末价现金终值 {v["terminal_count"]} 条；公司行动待核读数 {v["action_warning_count"]} 条。']
    lines += ['', '## 证据与边界', '',
              '- `manifest.json`：运行前输入及实现哈希；`result.json`：完整机器读数与产物哈希。',
              '- `pv_monthly.csv`：全量公司月、时点证据、估值、缺失与前向回报；`price_sources.csv`：CIK来源与补取记录。',
              '- `universe_pit_audit.csv` / `corporate_action_audit.csv`：样本时点与公司行动逐项审计。',
              '- 原腾讯方案的SEC季度股息再投保留，是申报数据近似口径；不能视为已核实所有实际除息日。',
              '- 不将无法证实的退市终值、非美元/ADR换算或提前生效状态纳入正式有效证据；未更改生产规则。',
              '- OI-159标普500分档表属于不同样本的补充研究；原四家公司smoke文件只验证管线。']
    (EXP / 'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:result[k] for k in ('outcome','reasons','company_months','status','universe_pit')}, ensure_ascii=False), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('prepare','value','report'))
    p.add_argument('--fetch', action='store_true')
    p.add_argument('--workers', type=int, default=16)
    a = p.parse_args()
    if a.stage == 'prepare':
        prepare(a.fetch)
    elif a.stage == 'value':
        value(a.workers)
    else:
        report()


if __name__ == '__main__':
    main()

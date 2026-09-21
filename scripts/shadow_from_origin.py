#!/usr/bin/env python3
"""Conditional, continuous shadow replay from the user's strategy return origin."""
from __future__ import annotations

import argparse
import ast
import copy
import inspect
import json
import math
from pathlib import Path
from statistics import mean
import tempfile

import backtest_valuation_strategy as bt
import shadow_portfolio as sh
from equity_bond_constraint import EquityBondConstraint

from corporate_actions import event_from_row, with_price_terms, validate_price_overrides, AMOUNTS, PRICE_FIELDS

ROOT = sh.ROOT
BOOK = ROOT / 'data/processed/shadow_portfolio/since_20260828'
EXP = ROOT / 'data/experiments/exp_shadow_origin_20260918'
CODE = ('shadow_from_origin.py', 'shadow_portfolio.py', 'backtest_valuation_strategy.py',
        'screen_daily_volume_price_signals.py', 'equity_bond_constraint.py', 'lot_cooldown.py', 'swap_chop_guard.py',
        'corporate_actions.py')


def hashes():
    return {p: sh.sha((ROOT / 'scripts' / p).read_bytes()) for p in CODE}


def historical_base(source):
    tree = ast.parse(source.read('scripts/sweep_backtest_configs.py').decode())
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'BASE' for t in n.targets))


def kwargs(base, execution_day):
    sig = inspect.signature(bt.run).parameters
    out = {}
    renamed = {'maintenance_ratio': 'maintenance', 'recover_ratio': 'recover_to', 'sell_line': 'sell_line_override'}
    ignored = {'fee_preset', 'no_artifacts', 'corr_window', 'daily_states', 'hold_states', 'universe_file'}
    for option, values in sh.base_options(base).items():
        if option in ignored or option.startswith('equity_bond_'):
            continue
        key = renamed.get(option, option)
        if key not in sig:
            raise ValueError(f'Unsupported historical parameter: {key}')
        if key in ('trend_ma', 'sell_trend_ma'):
            value = tuple(map(int, values))
        elif not values:
            value = True
        elif key in ('capital', 'x', 'sell_line_override'):
            value = float(values[0]) / (100 if key == 'x' else 1)
        elif isinstance(sig[key].default, int) and not isinstance(sig[key].default, bool):
            value = int(values[0])
        elif isinstance(sig[key].default, float):
            value = float(values[0])
        else:
            value = values[0]
        out[key] = value
    if execution_day >= '2026-09-15':
        out.setdefault('lot_cooldown_start', 'confirmed')
        out.setdefault('execution_consistency', 'signal')
    else:
        out['lot_cooldown_start'], out['execution_consistency'] = 'plan', 'legacy'
    out['lot_cooldown_shared'] = execution_day < '2026-09-02'
    if out['exec_delay'] != 1 or out['exec_price'] != 'close':
        raise ValueError('Only T+1 closing execution is supported')
    return out


def snapshot(day, revision, account):
    source = sh.Source(revision)
    base = historical_base(source)
    candidates = sh.csv_rows(source.read('data/processed/daily_buy_candidates.csv'))
    quotes = {r['security_code']: {k: r.get(k, '') for k in sh.QUOTE_FIELDS} for r in candidates}
    if len(quotes) != len(candidates) or any(r['trade_date'] not in ('', day) for r in candidates):
        raise ValueError('Duplicate or incorrectly dated candidates')
    if any(r['signal_state'] == 'data_error' for r in candidates):
        raise ValueError('Archived candidate data error')
    tracked = sh.csv_rows(source.read('data/processed/daily_holdings_tracking.csv'))
    for r in tracked:
        if r['as_of'] != day:
            raise ValueError('Incorrectly dated holding quote')
        if r['security_code'] not in quotes:
            quotes[r['security_code']] = dict(security_code=r['security_code'], security_name=r['security_name'],
                trade_date=day, close=r['close'], ma20=r['ma20'], ma60=r['ma60'], model_intrinsic_value='',
                model_pv='', hold_intrinsic_value='', hold_pv='', review_frozen='False')
    triage = sh.csv_rows(source.read('data/processed/a_share_attention_triage.csv'))
    members = sorted(r['security_code'] for r in triage if r['attention_class'] == 'worth_attention')
    if set(members) != {r['security_code'] for r in candidates}:
        raise ValueError('Point-in-time universe differs from candidate input')
    tiers = sh.csv_rows(source.read('data/processed/a_share_watchlist_quality_tiers.csv'))
    tactical = {r['security_code'] for r in tiers if r.get('quality_tier') == 'L3' and
                (not r.get('tactical_thesis', '').strip() or sh.live.SEC93_TACTICAL_NONE.match(r['tactical_thesis'].strip()))}
    blocked = tactical | {c for c, q in quotes.items() if q.get('review_frozen', '').lower() == 'true'}
    hs = sh.csv_rows(source.read('data/processed/a_share_holdings.csv'))
    holdings = {r['security_code']: dict(name=r['security_name'], shares=float(r['current_shares']),
                cost=float(r['cost_basis']), stop=float(r['entry_stop_price'])) for r in hs}
    action_rows = sh.csv_rows(source.read('data/raw/corporate_actions/a_share_corporate_actions.csv'))
    from corporate_actions import aggregate_actions
    price_data = source.read('data/reference/a_share_exright_terms.csv', optional=True)
    overrides = validate_price_overrides(sh.csv_rows(price_data)) if price_data else {}
    actions = {}
    for r in aggregate_actions(action_rows):
        d = r['ex_dividend_date']
        if d and d >= '2024-01-01' and r['security_code'] in set(quotes) | {'600919', '920599'}:
            actions.setdefault(r['security_code'], {})[d] = {k: v for k, v in with_price_terms(r, overrides=overrides).items() if k in (*AMOUNTS, *PRICE_FIELDS)}
    today = {c: a[day] for c, a in actions.items() if day in a}
    daily = source.read(f'data/interim/daily_corporate_actions_{day}.json', optional=True)
    if daily:
        today.update(json.loads(daily)['events'])
    options = sh.base_options(base)
    macro = source.read('data/reference/equity_bond_csi300.csv', optional=True)
    eb = None
    if 'equity_bond_mode' in options:
        if not macro:
            raise ValueError('Missing historical equity/bond observations')
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'macro.csv'; path.write_bytes(macro)
            obj = EquityBondConstraint(path, mode=options['equity_bond_mode'][0],
                metric=options['equity_bond_metric'][0], threshold=float(options['equity_bond_threshold'][0]),
                lower=float(options['equity_bond_lower'][0]), restore_above='equity_bond_restore_above' in options,
                release_threshold=float(options['equity_bond_release_threshold'][0]) if 'equity_bond_release_threshold' in options else None)
            signal, cap = obj.resolve(day)
            eb = dict(signal=vars(signal) if signal else None, cap=cap, mode=obj.mode)
    return dict(date=day, source_revision=source.revision, source_sha256=source.hashes,
                base=base, quotes=quotes, holdings=holdings, members=members, blocked=sorted(blocked),
                account=account, actions=today, all_actions=actions, equity_bond=eb)


def prepare():
    if (BOOK / 'manifest.json').exists():
        raise ValueError('Refusing to overwrite frozen inputs')
    refs = json.loads((EXP / 'sources.json').read_text())
    accounts = {r['as_of']: r for r in sh.csv_rows((ROOT / 'data/processed/portfolio_account_snapshot.csv').read_bytes())}
    origin = next(d for d, a in sorted(accounts.items()) if sh.number(a.get('strategy_base_net_assets_cny')))
    if min(refs) != origin:
        raise ValueError('Main shadow replay must start at the user-designated strategy origin')
    snapshots = [snapshot(d, r, accounts[d]) for d, r in sorted(refs.items())]
    if sorted(refs) != [d for d in sorted(accounts) if min(refs) <= d <= max(refs)]:
        raise ValueError('Incomplete account dates')
    # These early sessions still use a correlation filter. Preserve its full
    # potential candidate/holding input, not only the actual account's picks.
    codes = {'600919', '920599'}
    for s in snapshots:
        kw = kwargs(s['base'], s['date'])
        if kw['max_corr'] >= 1:
            continue
        codes.update(s['holdings'])
        for c, q in s['quotes'].items():
            pv, ma20, ma60 = (sh.number(q.get(k)) for k in ('model_pv', 'ma20', 'ma60'))
            if pv and pv <= 1 - kw.get('width', 0) and ma20 and ma60 and ma20 > ma60:
                codes.add(c)
    supplement = {}
    for c in sorted(codes):
        path = BOOK / 'supplement' / f'{c}.json'
        if path.exists():
            data = json.loads(path.read_text())
        else:
            exchange = 'BJ' if c.startswith(('92', '43', '83', '87')) else 'SH' if c.startswith(('6', '9')) else 'SZ'
            url, rows = sh.live.fetch_daily_rows_tencent(c, exchange, max(refs), 20, fq='')
            data = dict(code=c, source_url=url, retrieved_at_beijing=sh.now(), rows=rows)
            if not rows or rows[-1]['date'] < max(refs):
                raise ValueError(f'Stale supplemental prices: {c}')
            sh.save(path, data)
        supplement[c] = sh.sha(path.read_bytes())
        print(f'archived quote history {c}', flush=True)
    for s in snapshots:
        sh.save(BOOK / 'snapshots' / f'{s["date"]}.json', s)
    decisions = sh.csv_rows((ROOT / 'data/processed/a_share_workflow_decision_log.csv').read_bytes())
    correction = next(r for r in decisions if r['decision_id'] == 'holdings:2026-09-03:601225:correction01')
    sh.save(BOOK / 'opening_correction.json', correction)
    manifest = dict(created_at_beijing=sh.now(), baseline_date=min(refs), retrospective_through=max(refs),
        status='conditional_opening_reconstruction', code_sha256=hashes(),
        snapshots={s['date']: sh.sha((BOOK / 'snapshots' / f'{s["date"]}.json').read_bytes()) for s in snapshots},
        supplemental_prices=supplement,
        correction_sha256=sh.sha((BOOK / 'opening_correction.json').read_bytes()),
        scenarios={'missing_300_on_0831': 10100, 'missing_300_on_0828': 10400},
        fees=dict(bt.USER_FEES, stamp_mode='flat'),
        account_source_sha256=sh.sha((ROOT / 'data/processed/portfolio_account_snapshot.csv').read_bytes()))
    sh.save(BOOK / 'manifest.json', manifest)


class SignalCorrelations:
    def __init__(self, prices, actions, signal_day):
        self.signal_day = signal_day
        self.prices = prices
        acts = {c: {d: event_from_row(a)
                    for d, a in by_day.items()} for c, by_day in actions.items()}
        self.returns = bt.daily_returns({c: {d: p for d, p in ps.items() if d <= signal_day} for c, ps in prices.items()}, acts)
        self.calls = 0

    def get(self, a, b, day):
        self.calls += 1
        if a == b:
            return 1.
        if a not in self.returns or b not in self.returns:
            raise ValueError(f'Missing historical correlation input: {a}, {b}, {self.signal_day}')
        ra, rb = self.returns[a], self.returns[b]
        days = sorted(ra.keys() & rb.keys())[-252:]
        if len(days) < 120 or days[-1] != self.signal_day:
            raise ValueError(f'Insufficient/stale correlation input: {a}, {b}, {self.signal_day}')
        xa, xb = [ra[d] for d in days], [rb[d] for d in days]
        ma, mb = mean(xa), mean(xb)
        den = math.sqrt(sum((x-ma)**2 for x in xa) * sum((x-mb)**2 for x in xb))
        return sum((x-ma)*(y-mb) for x, y in zip(xa, xb)) / den if den else 0.


def market(snapshots, supplement):
    states, hold, prices, mas, gates, universe, actions = {}, {}, {}, {}, {}, [], {}
    for s in snapshots:
        day = s['date']; states[day], hold[day] = [], []
        gates[day] = set(s['blocked']); universe.append((day, set(s['members'])))
        for code, q in s['quotes'].items():
            p = sh.number(q.get('close'))
            if q.get('trade_date') != day or not p or p <= 0:
                continue
            prices.setdefault(code, {})[day] = p
            mas.setdefault(code, {})[day] = {n: sh.number(q.get('ma'+str(n))) for n in (20, 60) if sh.number(q.get('ma'+str(n))) is not None}
            for dest, prefix in ((states, 'model'), (hold, 'hold')):
                v, pv = sh.number(q.get(prefix+'_intrinsic_value')), sh.number(q.get(prefix+'_pv'))
                if v and pv and v > 0 and pv > 0:
                    dest[day].append((code, p, v, pv))
        for code, a in s['actions'].items():
            actions.setdefault(code, {})[day] = event_from_row(a)
    for code, rows in supplement.items():
        for s in snapshots:
            day = s['date']
            relevant = [r for r in rows if r['date'] <= day]
            if not relevant or relevant[-1]['date'] != day:
                continue  # A dated holding check below rejects any missing required mark.
            price = relevant[-1]['close']
            if day in prices.get(code, {}):
                if abs(prices[code][day] - price) > .011:
                    raise ValueError(f'Archived/supplemental close mismatch: {code} {day}')
                continue
            prices.setdefault(code, {})[day] = price
            # Supplement only missing marks, never use present-day valuation or membership.
            events = {d: event_from_row(a)
                      for d, a in s['all_actions'].get(code, {}).items()}
            adjusted = sh.live.rebase_price_rows(relevant, code, day, events=events)
            mas.setdefault(code, {})[day] = {n: mean(r['close'] for r in adjusted[-n:]) for n in (20, 60) if len(adjusted) >= n}
    return dict(states=states, hold_states=hold, prices=prices, mas=mas, buy_blocked=gates, universe=universe, actions=actions)


def replay(snapshots, supplement, manifest, opening_shares):
    data = market(snapshots, supplement)
    first = snapshots[0]; day0 = first['date']
    seed = bt.Portfolio(cash=float(first['account']['cash_cny']), debt=float(first['account']['margin_debt_cny']))
    for code, h in first['holdings'].items():
        shares, cost = h['shares'], h['cost']
        if code == '601225':
            shares = opening_shares
            if opening_shares == 10400:
                cost = (5500 * 25.595 + 4900 * 27.07) / 10400
        seed.lots[code] = bt.Lot(code, day0, 0., 0., 0., 0., 0., shares=shares,
            invested=shares*cost, avg_cost=cost, bought_shares=shares, buys=1,
            entry_stop=h['stop'], entry_stop_ma=60, sublots=[[day0, shares, 0.]])
    capital = seed.equity({c: ps[day0] for c, ps in data['prices'].items() if day0 in ps})
    rows, fills, states, checks = [], [], [], []
    cooldown, fee_total, corr_calls = {}, 0., 0
    supplement_prices = {c: {r['date']: r['close'] for r in rs} for c, rs in supplement.items()}
    for prev, current in zip(snapshots, snapshots[1:]):
        before, day = prev['date'], current['date']
        kw = kwargs(prev['base'], day)
        eb = prev['equity_bond']
        constraint = sh.ArchivedConstraint([dict(date=s['date'], equity_bond=s['equity_bond'])
                    for s in (prev, current)], eb['mode']) if eb else None
        correlation = SignalCorrelations(supplement_prices, prev['all_actions'], before) if kw['max_corr'] < 1 else None
        marks = {c: ps[before] for c, ps in data['prices'].items() if before in ps}
        bt.FEES.update(manifest['fees'], paid=0.); bt.SLIPPAGE = 0.
        ledger, observed, end = [], [], []
        kw.update(data, since=before, until=day, capital=seed.equity(marks), initial_portfolio=seed,
                  initial_cooldown=cooldown, final_portfolio=end, liquidate_at_end=False,
                  equity_bond=constraint, corr=correlation, ledger=ledger, portfolio_snapshots=observed)
        # A closing scan may be revised overnight/weekend. Its membership is
        # actionable on the NEXT execution date, not that same day's closing fill.
        kw['universe'] = [(before, set(prev['members']))]
        result = bt.run(**kw)
        if len(result['equity']) != 2 or len(observed) != 2 or len(end) != 1:
            raise ValueError('Incomplete daily continuation')
        daily_fills = [dict(date=r['date'], security_code=r['security_code'], side='buy' if r['action']=='买入' else 'sell',
                           shares=float(r['shares']), price=float(r['price']), reason=r['reason']) for r in ledger if float(r['shares']) > 0]
        q0 = {c: {'close': ps[before]} for c, ps in data['prices'].items() if before in ps}
        q1 = {c: {'close': ps[day]} for c, ps in data['prices'].items() if day in ps}
        pnl, intraday = sh.economics(observed[0]['holdings'], observed[1]['holdings'], q0, q1, daily_fills, current['actions'])
        costs = sum(observed[1][k] - observed[0][k] for k in ('interest_paid', 'fees_paid', 'dividend_tax_paid'))
        delta = result['equity'][1][1] - result['equity'][0][1]
        if abs(pnl + intraday - costs - delta) > .03:
            raise ValueError(f'Independent shadow accounting failed on {day}')
        checks.append(dict(date=day, price_and_dividend_pnl=pnl, trade_price_pnl=intraday, costs=costs, net_change=delta,
                           residual=pnl+intraday-costs-delta))
        for idx in (0, 1) if not rows else (1,):
            curve, state = result['equity'][idx], copy.deepcopy(observed[idx])
            state['fees_paid'] += fee_total
            if any(curve[0] not in data['prices'].get(c, {}) for c in state['holdings']):
                raise ValueError('Missing same-day shadow mark')
            state['net_assets'] = curve[1]; states.append(state)
            rows.append(dict(date=curve[0], net_assets=curve[1], unit_nav=curve[1]/capital,
                             return_pct=(curve[1]/capital-1)*100, debt=state['debt'], cash=state['cash'],
                             opening_capital=capital, opening_coal_shares=opening_shares))
        fee_total += result['fees']
        seed = end[0]
        cooldown = dict(buy=observed[-1]['buy_counters'], sell=observed[-1]['sell_counters'])
        fills.extend(daily_fills)
        corr_calls += correlation.calls if correlation else 0
    return rows, fills, states, checks, corr_calls


def opening_confirmation(manifest):
    digest = manifest.get('opening_confirmation_sha256')
    if not digest:
        if len(manifest['scenarios']) != 2:
            raise ValueError('A single opening scenario requires confirmation evidence')
        return None
    path = BOOK/'opening_confirmation.json'
    if sh.sha(path.read_bytes()) != digest:
        raise ValueError('Opening confirmation evidence changed')
    evidence = json.loads(path.read_text())
    shares = evidence['shares_before_0828'] + evidence['confirmed_buys']['2026-08-28']
    if (evidence['baseline_date'] != manifest['baseline_date'] or
            evidence['opening_shares'] != shares or
            shares + evidence['confirmed_buys']['2026-08-31'] != evidence['shares_confirmed_on_0903'] or
            manifest['scenarios'] != {evidence['selected_scenario']: shares}):
        raise ValueError('Confirmed fills and opening scenario do not reconcile')
    return evidence


def corrected_actions(snapshots, correction):
    """Apply an evidenced event correction to replay copies; archived quotes stay fixed."""
    result = copy.deepcopy(snapshots)
    for snapshot in result:
        if snapshot['date'] > correction['through']:
            continue
        for code, events in correction['events'].items():
            for day, event in events.items():
                if correction.get('availability') == 'per_event':
                    notice = correction['notice_dates'][code][day]
                    if notice > day:
                        raise ValueError('Historical action correction is not yet available')
                    if day > snapshot['date'] or notice > snapshot['date']:
                        continue
                elif day > correction['known_by'] or day > snapshot['date']:
                    raise ValueError('Historical action correction is not yet available')
                if code in snapshot['all_actions']:
                    snapshot['all_actions'][code][day] = event
                if day == snapshot['date']:
                    snapshot['actions'][code] = event
    return result


def load():
    manifest = json.loads((BOOK/'manifest.json').read_text())
    if manifest['code_sha256'] != hashes():
        raise ValueError('Frozen replay code changed')
    opening_confirmation(manifest)
    snapshots = []
    for day, digest in sorted(manifest['snapshots'].items()):
        path = BOOK/'snapshots'/f'{day}.json'
        if sh.sha(path.read_bytes()) != digest:
            raise ValueError('Archived input changed')
        snapshots.append(json.loads(path.read_text()))
    supplement = {}
    for code, digest in manifest['supplemental_prices'].items():
        path = BOOK/'supplement'/f'{code}.json'
        if sh.sha(path.read_bytes()) != digest:
            raise ValueError('Supplemental price archive changed')
        supplement[code] = json.loads(path.read_text())['rows']
    for name, digest in sorted(manifest.get('price_updates', {}).items()):
        path = BOOK/name
        if sh.sha(path.read_bytes()) != digest:
            raise ValueError('Supplemental price update changed')
        update = json.loads(path.read_text())
        supplement[update['code']] = merge_prices(supplement.get(update['code'], []), update['rows'])
    if sh.sha((BOOK/'opening_correction.json').read_bytes()) != manifest['correction_sha256']:
        raise ValueError('Opening correction evidence changed')
    for name, digest in manifest.get('action_corrections', {}).items():
        path = BOOK/name
        if sh.sha(path.read_bytes()) != digest:
            raise ValueError('Historical action correction evidence changed')
        snapshots = corrected_actions(snapshots, json.loads(path.read_text()))
    for name, digest in manifest.get('code_migrations', {}).items():
        if sh.sha((BOOK/name).read_bytes()) != digest:
            raise ValueError('Replay code migration evidence changed')
    return manifest, snapshots, supplement


def merge_prices(old, new):
    rows = {r['date']: r for r in old}
    for row in new:
        if row['date'] in rows and abs(rows[row['date']]['close']-row['close']) > .011:
            raise ValueError('Historical supplemental close was revised')
        rows.setdefault(row['date'], row)
    return [r for _,r in sorted(rows.items())]


def capture(day):
    manifest, snapshots, supplement = load()
    if not day or day <= snapshots[-1]['date']:
        raise ValueError('Capture only appends a completed new date')
    publication = json.loads((ROOT/'data/processed/daily_execution_publication.json').read_text())
    if publication.get('status') != 'complete' or publication.get('as_of') != day:
        raise ValueError('Production publication must be complete and dated correctly')
    accounts = {r['as_of']: r for r in sh.csv_rows((ROOT/'data/processed/portfolio_account_snapshot.csv').read_bytes())}
    if [d for d in sorted(accounts) if d > snapshots[-1]['date']] != [day]:
        raise ValueError('Archive every intervening account date first')
    if float(accounts[day]['external_cash_flow_cny']) != 0:
        raise ValueError('External cash flow requires an explicit shadow allocation rule')
    before = sh.real_hashes()
    current = snapshot(day, None, accounts[day])
    required = set(snapshots[-1]['quotes']) - set(current['quotes'])
    for name in manifest['scenarios']:
        state = json.loads((BOOK/name/'states.json').read_text())[-1]
        if state['date'] != snapshots[-1]['date']:
            raise ValueError('Replay existing inputs before capturing another day')
        required.update(set(state['holdings'])-set(current['quotes']))
    pending = {}
    for code in sorted(required):
        exchange = 'BJ' if code.startswith(('92','43','83','87')) else 'SH' if code.startswith(('6','9')) else 'SZ'
        url, rows = sh.live.fetch_daily_rows_tencent(code, exchange, day, 20, fq='')
        if not rows or rows[-1]['date'] != day:
            raise ValueError(f'Missing required supplemental closing quote: {code}')
        pending[code] = dict(code=code,source_url=url,retrieved_at_beijing=sh.now(),rows=rows)
        supplement[code] = merge_prices(supplement.get(code,[]),rows)
    for shares in manifest['scenarios'].values():
        replay(snapshots+[current],supplement,manifest,shares)
    if before != sh.real_hashes():
        raise ValueError('Production inputs changed during capture')
    for code,value in pending.items():
        name=f'supplement/updates/{day}_{code}.json'
        path=BOOK/name
        if path.exists():
            raise ValueError('Refusing to overwrite a supplemental archive')
        sh.save(path,value)
        manifest.setdefault('price_updates',{})[name]=sh.sha(path.read_bytes())
    path=BOOK/'snapshots'/f'{day}.json'
    if path.exists():
        raise ValueError('Refusing to overwrite a snapshot')
    sh.save(path,current);manifest['snapshots'][day]=sh.sha(path.read_bytes())
    sh.save(BOOK/'manifest.json',manifest)
    print(f'Archived {day}; run to publish the comparison')


def run():
    before = sh.real_hashes()
    manifest, snapshots, supplement = load()
    outcomes = {}
    for name, shares in manifest['scenarios'].items():
        result = replay(snapshots, supplement, manifest, shares)
        prefix = replay(snapshots[:-1], supplement, manifest, shares)
        if result[0][:-1] != prefix[0] or result[2][:-1] != prefix[2] or [f for f in result[1] if f['date'] < snapshots[-1]['date']] != prefix[1]:
            raise ValueError('Future inputs changed the existing shadow path')
        outcomes[name] = result
    if before != sh.real_hashes():
        raise ValueError('Production inputs changed')
    for name, (rows, fills, states, checks, calls) in outcomes.items():
        path = BOOK/name; path.mkdir(exist_ok=True)
        sh.write_csv(path/'equity.csv', rows); sh.write_csv(path/'fills.csv', fills)
        sh.write_csv(path/'accounting.csv', checks); sh.save(path/'states.json', states)
    real0 = float(snapshots[0]['account']['net_assets_cny'])
    comparison = []
    for i, s in enumerate(snapshots):
        real = float(s['account']['net_assets_cny'])
        row = dict(date=s['date'], actual_epoch=s['account']['strategy_epoch'], actual_net_assets=real,
                   actual_return_pct=(real/real0-1)*100)
        for name, outcome in outcomes.items():
            row[name+'_return_pct'] = outcome[0][i]['return_pct']
            row[name+'_net_assets'] = outcome[0][i]['net_assets']
        comparison.append(row)
    sh.write_csv(BOOK/'daily_comparison.csv', comparison)
    rules = [dict(signal_date=s['date'], execution_date=t['date'], base=s['base'],
                  effective_overrides=json.dumps({k:v for k,v in kwargs(s['base'],t['date']).items()
                   if k in ('execution_consistency','lot_cooldown_start','lot_cooldown_shared')},ensure_ascii=False))
             for s,t in zip(snapshots,snapshots[1:])]
    sh.write_csv(BOOK/'rule_schedule.csv', rules)
    sh.save(BOOK/'verification.json',dict(days=len(comparison), trading_intervals=len(comparison)-1,
        accounting_closed=True, prefix_invariance=True, production_unchanged=True,
        production_sha256=before, code_sha256=hashes(), correlation_calls={k:v[-1] for k,v in outcomes.items()}))
    last = comparison[-1]
    confirmed = opening_confirmation(manifest)
    names = list(outcomes)
    labels = {name: ('已确认影子组合' if confirmed else
              '300股漏记在' + ('08-28' if name.endswith('0828') else '08-31')) for name in names}
    def table_row(cells):
        return '| ' + ' | '.join(map(str, cells)) + ' |'
    title = '期初股数已确认' if confirmed else '期初持仓两种情景'
    explanation = (
        '用户补充确认08-28买入4,900股、08-31买入5,100股。原记录分别为4,600股、5,100股，'
        '故少记300股发生在08-28。原有5,500股→08-28收盘10,400股→08-31收盘15,500股，'
        '与09-03订正一致。08-31漏记假设已排除，旧路径仅留作历史证据。'
        if confirmed else
        '09-03用户确认陕西煤业15,500股、成本26.707，原记15,200股。原决策日志注明：少记的300股落在08-28还是08-31无法判定，暂保留两个期初情景。')
    lines = [f'# 从2026-08-28开始的影子组合：{title}', '',
        '**本表替代将09-14当成主起点的解释。09-14起的E4报告仅保留作分段对照。**', '',
        f'08-28收盘至{snapshots[-1]["date"]}，共{len(snapshots)-1}个交易日；截至{manifest["retrospective_through"]}为历史回放，其后为前向记录。参数随原日版本变化，影子持仓、资金、批次与冷却连续递推，未按实盘重置。', '',
        '## 已找到的订正', '',
        explanation, '',
        '09-01的8,016元和09-02的7,830元分别等于300×26.72、300×26.10，已闭合。正式账户的2,811,530.99元基准及收益不变。影子用收盘持仓净资产作分母，未将券商与持仓的差额当作现金。这是有条件回放，不声称初始账户已经完全对账。', '',
        table_row(['指标'] + [labels[n] for n in names] + ['实盘报告']),
        table_row(['---'] + ['---:'] * (len(names)+1)),
        table_row(['08-28陕西煤业股数'] + [f'{manifest["scenarios"][n]:,}' for n in names] + ['10,400' if confirmed else '日期未定'])]
    for label, index, key, fmt, real in (
            ('初始净资产/分母', 0, 'net_assets', ',.2f', real0),
            ('期末净资产', -1, 'net_assets', ',.2f', last['actual_net_assets']),
            ('累计收益', -1, 'return_pct', '.4f', last['actual_return_pct'])):
        suffix = '%' if key == 'return_pct' else ''
        lines.append(table_row([label] + [format(outcomes[n][0][index][key], fmt)+suffix for n in names]
                               + [format(real, fmt)+suffix]))
    lines += ['', '## 逐日累计收益', '',
              table_row(['日期'] + [labels[n] for n in names] + ['实盘报告']),
              table_row(['---'] + ['---:'] * (len(names)+1))]
    for r in comparison:
        lines.append(table_row([r['date']] + [f'{r[n+"_return_pct"]:.4f}%' for n in names]
                               + [f'{r["actual_return_pct"]:.4f}%']))
    lines += ['', '## 解释范围', '',
        ('- 期初股数与漏记日期已确认；该路径沿用原10,400股情景，后续仅更新这条路径。'
         if confirmed else '- 期初情景解释的是记录歧义，并非置信区间或最坏情况范围。'),
        '- 使用原日名单、双侧估值、均线、闸门与BASE参数；用现有修正记账引擎承接历史参数，不刻意复现历史软件缺陷。相关性按信号日截止的252日收益计算，历史补取价格与原归档收盘交叉核验。',
        '- 模拟按次日收盘成交，券商实时授信算法未重建；融资沿用比例公式。收益差异包含持仓、规则执行、融资与口径因素，不能全部归为人工执行。',
        '- 原始持仓建立前已收股息的递延税批次不全；08-28之后的公司行动、模拟成交与计息持续记账。',
        '- 补计300股后的资产残差：08-28为792.65元，08-31为1,510.99元。股份日期确认不等于这两笔残差已解释，未伪造现金弥补。',
        '- 原始8月末与9月初交易有整仓卖出、清单外加仓等裁量，不能把此前实盘收益拼接成影子收益。逐笔影子成交见各情景fills.csv。', '',
        '输入与证据：manifest.json、snapshots/、supplement/、opening_correction.json、rule_schedule.csv、daily_comparison.csv、verification.json。'
        + (' 本次确认见opening_confirmation.json；旧双情景版本见Git c13edc82。' if confirmed else ''), '']
    (BOOK/'report.md').write_text('\n'.join(lines))
    print(json.dumps(last,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare','capture','run'))
    p.add_argument('--as-of')
    args=p.parse_args()
    if args.command=='prepare':
        prepare()
    elif args.command=='capture':
        capture(args.as_of)
    else:
        run()

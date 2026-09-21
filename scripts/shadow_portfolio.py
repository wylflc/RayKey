#!/usr/bin/env python3
"""Archive live inputs and run an independently evolving, seeded shadow account.

No network requests and no writes to real holdings, plans or execution receipts.
Run init/capture only after the daily production inputs have been reconciled.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import io
import json
import math
import re
import shlex
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import backtest_valuation_strategy as bt
import screen_daily_volume_price_signals as live
import sweep_backtest_configs as sweep
from equity_bond_constraint import EquityBondConstraint

from corporate_actions import event_from_row

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOOK = ROOT / 'data/processed/shadow_portfolio/e4'
PROTECTED = ('shadow_portfolio.py', 'backtest_valuation_strategy.py',
             'sweep_backtest_configs.py', 'screen_daily_volume_price_signals.py',
             'equity_bond_constraint.py', 'lot_cooldown.py', 'swap_chop_guard.py')
REAL_FILES = ('a_share_holdings.csv', 'portfolio_account_snapshot.csv',
              'cooldown_executions.csv', 'daily_cooldown_state.csv',
              'daily_entry_plan.csv', 'daily_sell_plan.csv', 'daily_buy_candidates.csv')
QUOTE_FIELDS = ('security_code', 'security_name', 'trade_date', 'close', 'mark_close',
                'mark_date', 'tradable', 'ma20', 'ma60', 'model_intrinsic_value',
                'model_pv', 'hold_intrinsic_value', 'hold_pv', 'review_frozen',
                'data_source', 'screened_at_utc', 'signal_state')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(data)
    temporary.replace(path)


def csv_rows(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))


def write_csv(path: Path, rows: list[dict], fields=()) -> None:
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else fields)
        writer.writeheader()
        writer.writerows(rows)


def number(value, default=None):
    if value is None or value == '':
        return default
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'Nonfinite input: {value}')
    return result


def code_hashes() -> dict:
    return {p: sha((ROOT / 'scripts' / p).read_bytes()) for p in PROTECTED}


def real_hashes() -> dict:
    return {p: sha((ROOT / 'data/processed' / p).read_bytes()) for p in REAL_FILES}


def base_options(base: str) -> dict:
    result, key = {}, None
    for token in shlex.split(base):
        if token.startswith('--'):
            key = token[2:].replace('-', '_')
            if key in result:
                raise ValueError(f'Duplicate BASE option: {key}')
            result[key] = []
        elif key:
            result[key].append(token)
        else:
            raise ValueError(f'Invalid BASE token: {token}')
    return result


def engine_kwargs(base: str) -> dict:
    """Use the actual BASE values; fail on new options requiring adapter review."""
    signature = inspect.signature(bt.run).parameters
    renamed = {'maintenance_ratio': 'maintenance', 'recover_ratio': 'recover_to'}
    inputs = {'daily_states', 'hold_states', 'universe_file', 'corr_window', 'no_artifacts', 'fee_preset'}
    result = {}
    for option, values in base_options(base).items():
        if option in inputs or option.startswith('equity_bond_'):
            continue
        key = renamed.get(option, option)
        if key not in signature:
            raise ValueError(f'Unsupported BASE option: {option}')
        if key in ('trend_ma', 'sell_trend_ma'):
            value = tuple(map(int, values))
        elif not values:
            value = True
        elif len(values) != 1:
            raise ValueError(f'Unsupported multi-value BASE option: {option}')
        elif key in ('x', 'capital'):
            value = float(values[0]) / (100 if key == 'x' else 1)
        elif isinstance(signature[key].default, bool):
            raise ValueError(f'Unexpected boolean value: {option}')
        elif isinstance(signature[key].default, int):
            value = int(values[0])
        elif isinstance(signature[key].default, float):
            value = float(values[0])
        else:
            value = values[0]
        result[key] = value
    if result.get('exec_delay') != 1 or result.get('exec_price') != 'close':
        raise ValueError('This book requires T+1 closing-price execution')
    if result.get('max_corr') != 1.0:
        raise ValueError('Correlation filtering needs archived price histories')
    if base_options(base).get('fee_preset') != ['user']:
        raise ValueError('Unreviewed fee preset')
    return result


class Source:
    def __init__(self, revision=None):
        self.revision = (subprocess.check_output(['git', 'rev-parse', revision], cwd=ROOT,
                                                text=True).strip() if revision else None)
        self.hashes = {}

    def read(self, path, optional=False):
        if self.revision:
            result = subprocess.run(['git', 'show', f'{self.revision}:{path}'], cwd=ROOT, capture_output=True)
            if result.returncode:
                if optional:
                    return None
                raise ValueError(f'Missing historical input: {path} at {self.revision}')
            data = result.stdout
        else:
            target = ROOT / path
            if optional and not target.exists():
                return None
            data = target.read_bytes()
        self.hashes[path] = sha(data)
        return data


def capture_snapshot(day: str, source: Source, base: str, *, baseline=False) -> dict:
    candidates = csv_rows(source.read('data/processed/daily_buy_candidates.csv'))
    if not candidates or day not in {r['trade_date'] for r in candidates} or any(
            r['trade_date'] != day and not (r['trade_date'] == '' and
            r.get('signal_state') == 'insufficient_price_history') for r in candidates):
        raise ValueError(f'Candidate snapshot does not exclusively cover {day}')
    quotes = {r['security_code']: {k: r.get(k, '') for k in QUOTE_FIELDS} for r in candidates}
    if len(quotes) != len(candidates):
        raise ValueError('Duplicate candidate codes')
    if any(r.get('signal_state') == 'data_error' for r in candidates):
        raise ValueError('Unresolved market data errors in candidate snapshot')
    tracked = csv_rows(source.read('data/processed/daily_holdings_tracking.csv'))
    holdings = csv_rows(source.read('data/processed/a_share_holdings.csv'))
    if {r['security_code'] for r in holdings} - quotes.keys():
        raise ValueError('Out-of-pool held quotes require an explicit archived market snapshot')
    if tracked and {r['as_of'] for r in tracked} != {day}:
        raise ValueError('Holdings tracking date mismatch')
    accounts = csv_rows(source.read('data/processed/portfolio_account_snapshot.csv'))
    selected = [r for r in accounts if r['as_of'] == day]
    if len(selected) != 1:
        raise ValueError('Require exactly one account snapshot')
    account = {k: number(selected[0][k]) for k in
               ('net_assets_cny', 'total_assets_cny', 'cash_cny', 'margin_debt_cny', 'external_cash_flow_cny')}
    if any(v is None for v in account.values()) or account['external_cash_flow_cny'] != 0:
        raise ValueError('Missing account value or external flow: reconcile before continuing')
    h = {r['security_code']: dict(name=r['security_name'], shares=number(r['current_shares']),
                                 cost=number(r['cost_basis']), stop=number(r['entry_stop_price'])) for r in holdings}
    if any(v[k] is None for v in h.values() for k in ('shares', 'cost', 'stop')):
        raise ValueError('Incomplete inherited holding')
    market_value = sum(v['shares'] * number(quotes[c]['close']) for c, v in h.items())
    if abs(market_value + account['cash_cny'] - account['total_assets_cny']) > .011:
        raise ValueError(f'{day}: actual holdings do not reconcile to reported assets')
    if abs(account['total_assets_cny'] - account['margin_debt_cny'] - account['net_assets_cny']) > .011:
        raise ValueError('Account balance identity failed')
    triage = csv_rows(source.read('data/processed/a_share_attention_triage.csv'))
    members = sorted(r['security_code'] for r in triage if r['attention_class'] == 'worth_attention')
    if set(members) != set(quotes):
        raise ValueError('Candidate quote universe differs from point-in-time membership')
    tiers = source.read('data/processed/a_share_watchlist_quality_tiers.csv')
    macro = source.read('data/reference/equity_bond_csi300.csv')
    options = base_options(base)
    with tempfile.TemporaryDirectory(prefix='shadow-input-') as tmp:
        tier_file, macro_file = Path(tmp) / 'tiers.csv', Path(tmp) / 'macro.csv'
        tier_file.write_bytes(tiers); macro_file.write_bytes(macro)
        tactical = sorted(live.load_tactical_gate_codes(tier_file))
        constraint = EquityBondConstraint(macro_file,
            mode=options['equity_bond_mode'][0], metric=options['equity_bond_metric'][0],
            threshold=float(options['equity_bond_threshold'][0]), lower=float(options['equity_bond_lower'][0]),
            restore_above='equity_bond_restore_above' in options,
            release_threshold=float(options['equity_bond_release_threshold'][0]))
        signal, cap = constraint.resolve(day)
    actions = json.loads(source.read(f'data/interim/daily_corporate_actions_{day}.json'))
    if actions['signal_date'] != day:
        raise ValueError('Corporate-action date mismatch')
    fills, fill_evidence, amount_checks = [], None, []
    for name in (f'data/interim/daily_execution_reconciliation_{day}.json',
                 f'data/interim/daily_execution_{day}.json'):
        data = source.read(name, optional=True)
        if data is None:
            continue
        value = json.loads(data)
        if 'trades' not in value:
            continue
        fill_evidence = name
        for row in value['trades']:
            fills.append(dict(date=day, security_code=row['security_code'], side=row['side'],
                              shares=number(row['shares']), price=number(row['price'])))
            amount = number(row.get('amount_cny', row.get('gross_amount_cny')))
            calculated = number(row['shares']) * number(row['price'])
            if amount is not None and abs(amount - calculated) > .011:
                amount_checks.append(dict(date=day, security_code=row['security_code'],
                    recorded_amount=amount, shares_times_price=calculated,
                    recorded_minus_calculated=amount-calculated, source=name))
        break
    log = source.read('docs/000_daily_scan_log.md').decode()
    section = next((s for s in re.split(r'(?m)^## 每日扫描 ', log)[1:] if s.startswith(day)), '')
    no_trades = bool(re.search(r'无成交|未成交|没有成交', section))
    if not baseline and not fills and not no_trades:
        raise ValueError(f'{day}: neither recorded trades nor explicit no-trade confirmation')
    cooldown = csv_rows(source.read('data/processed/daily_cooldown_state.csv'))
    match = re.search(r'(?:券商)?可用保证金\s*[=＝]?\s*([−-]?[0-9,]+(?:\.\d+)?)', selected[0]['note'])
    margin = float(match[1].replace(',', '').replace('−', '-')) if match else None
    return dict(date=day, captured_at_beijing=now(), source_revision=source.revision,
                sources=source.hashes, quotes=quotes, members=members,
                blocked=sorted(c for c, q in quotes.items() if str(q['review_frozen']).lower() == 'true'),
                tactical_gated=tactical, account=account, actual_holdings=h, actual_fills=fills,
                fill_evidence=fill_evidence, no_trades_confirmed=no_trades,
                trade_amount_discrepancies=amount_checks, reported_available_margin=margin,
                actual_strategy_epoch=selected[0]['strategy_epoch'],
                cooldown=cooldown, actions=actions['events'],
                equity_bond=dict(signal=vars(signal) if signal else None, cap=cap),
                available_account_dates=[r['as_of'] for r in accounts if r['as_of'] <= day])


class ArchivedConstraint:
    def __init__(self, snapshots, mode):
        self.mode = mode
        self.inputs = {s['date']: s['equity_bond'] for s in snapshots}

    def resolve(self, day):
        value = self.inputs[day]
        return SimpleNamespace(**value['signal']) if value['signal'] else None, value['cap']


def simulate(snapshots: list[dict], protocol: dict):
    first, last = snapshots[0], snapshots[-1]
    states, hold_states, prices, mas, actions, gates, universe = {}, {}, {}, {}, {}, {}, []
    for snapshot in snapshots:
        day = snapshot['date']
        states[day], hold_states[day] = [], []
        universe.append((day, set(snapshot['members'])))
        gates[day] = set(snapshot['blocked']) | set(snapshot['tactical_gated'])
        for code, q in snapshot['quotes'].items():
            close = number(q.get('close'))
            tradable = str(q.get('tradable', 'True')).lower() != 'false'
            if close is None or close <= 0 or not tradable or q.get('trade_date') != day:
                # Require supplemental marked quotes before a held suspension can be evaluated.
                continue
            prices.setdefault(code, {})[day] = close
            mas.setdefault(code, {})[day] = {n: number(q['ma' + str(n)]) for n in (20, 60)
                                            if number(q.get('ma' + str(n))) is not None}
            for dest, prefix in ((states, 'model'), (hold_states, 'hold')):
                value, pv = number(q.get(prefix + '_intrinsic_value')), number(q.get(prefix + '_pv'))
                if value and pv is not None and pv > 0:
                    dest[day].append((code, close, value, pv))
        for code, event in snapshot['actions'].items():
            actions.setdefault(code, {})[day] = event_from_row(event)
    seed = bt.Portfolio(cash=first['account']['cash_cny'], debt=first['account']['margin_debt_cny'])
    for code, h in first['actual_holdings'].items():
        # entry_date is a synthetic accounting origin; old FIFO dividend history is unavailable.
        seed.lots[code] = bt.Lot(code, first['date'], 0., 0., 0., 0., 0.,
            shares=h['shares'], invested=h['shares'] * h['cost'], avg_cost=h['cost'],
            bought_shares=h['shares'], buys=1, entry_stop=h['stop'], entry_stop_ma=60,
            sublots=[[first['date'], h['shares'], 0.]])
    if any(int(r.get('remaining_skips') or 0) for r in first['cooldown']):
        raise ValueError('Nonzero initial cooldown requires a separate seeded-counter adapter')
    for snapshot in snapshots[1:]:
        if set(seed.lots) & set(snapshot['actions']):
            raise ValueError('An inherited lot has a corporate action; obtain its original FIFO history first')
    kwargs = engine_kwargs(protocol['base'])
    kwargs.update(states=states, hold_states=hold_states, prices=prices, mas=mas, actions=actions,
                  since=first['date'], until=last['date'], capital=first['account']['net_assets_cny'],
                  initial_portfolio=seed, buy_blocked=gates, universe=universe,
                  equity_bond=ArchivedConstraint(snapshots, base_options(protocol['base'])['equity_bond_mode'][0]),
                  liquidate_at_end=False)
    bt.FEES.update(protocol['fees'], paid=0.)
    bt.SLIPPAGE = 0.
    ledger, observed = [], []
    result = bt.run(**kwargs, ledger=ledger, portfolio_snapshots=observed)
    # The engine may mark suspended positions at stale quotes. This book only publishes
    # fully contemporaneous marks until explicit suspension records are supported.
    for state in observed:
        missing = [c for c in state['holdings'] if state['date'] not in prices.get(c, {})]
        if missing:
            raise ValueError(f'Missing same-day shadow marks: {state["date"]} {missing}')
    fills = [dict(date=r['date'], security_code=r['security_code'],
                  side='buy' if r['action'] == '买入' else 'sell', shares=float(r['shares']),
                  price=float(r['price']), reason=r['reason'])
             for r in ledger if float(r['shares']) > 0]
    return result, observed, fills


def economics(previous, current, quotes0, quotes1, fills, actions):
    """Independent mark/trade identity. Positive residual is an unclassified cost."""
    pnl, trade_pnl, changes = 0., 0., {}
    for code, h in previous.items():
        event = actions.get(code, {})
        ratio, cash = float(event.get('share_ratio', 0)), float(event.get('cash_per_share', 0))
        rr, rp = float(event.get('rights_ratio', 0)), float(event.get('rights_price', 0))
        q0, q1 = number(quotes0[code]['close']), number(quotes1[code]['close'])
        pnl += h['shares'] * ((1 + ratio + rr) * q1 - q0 + cash - rr * rp)
        changes[code] = h['shares'] * (1 + ratio + rr)
    for fill in fills:
        code, qty, price = fill['security_code'], fill['shares'], fill['price']
        if fill['side'] not in ('buy', 'sell') or qty <= 0 or price <= 0:
            raise ValueError('Invalid actual or shadow fill')
        sign = 1 if fill['side'] == 'buy' else -1
        changes[code] = changes.get(code, 0.) + sign * qty
        trade_pnl += sign * qty * (number(quotes1[code]['close']) - price)
    expected = {c: q for c, q in changes.items() if abs(q) > 1e-8}
    actual = {c: h['shares'] for c, h in current.items() if h['shares'] > 0}
    if expected.keys() != actual.keys() or any(abs(expected[c] - actual[c]) > 1e-7 for c in expected):
        raise ValueError(f'Holdings changes do not reconcile to recorded fills: {expected} vs {actual}')
    return pnl, trade_pnl


def compare(snapshots, result, observed, fills):
    if not (len(snapshots) == len(result['equity']) == len(observed)):
        raise ValueError('Incomplete shadow path')
    capital = snapshots[0]['account']['net_assets_cny']
    rows, attribution = [], []
    previous_shadow = previous_real = capital
    real_peak = shadow_peak = capital
    for i, (snapshot, curve, state) in enumerate(zip(snapshots, result['equity'], observed)):
        day, shadow, real = snapshot['date'], curve[1], snapshot['account']['net_assets_cny']
        if day != curve[0] or day != state['date']:
            raise ValueError('Shadow dates differ from archived snapshots')
        real_peak, shadow_peak = max(real_peak, real), max(shadow_peak, shadow)
        rows.append(dict(date=day, shadow_net_assets=shadow, actual_net_assets=real,
                         shadow_unit_nav=shadow / capital, actual_unit_nav=real / capital,
                         shadow_return=shadow / capital - 1, actual_return=real / capital - 1,
                         shadow_daily_return=shadow / previous_shadow - 1,
                         actual_daily_return=real / previous_real - 1,
                         shadow_minus_actual_cny=shadow - real,
                         shadow_minus_actual_pp=(shadow - real) / capital * 100,
                         shadow_drawdown=shadow / shadow_peak - 1, actual_drawdown=real / real_peak - 1,
                         shadow_cash=state['cash'], shadow_debt=state['debt'],
                         actual_debt=snapshot['account']['margin_debt_cny'],
                         reported_available_margin=snapshot['reported_available_margin']))
        if i:
            previous = snapshots[i - 1]
            shadow_fills = [r for r in fills if r['date'] == day]
            sp, st = economics(observed[i - 1]['holdings'], state['holdings'], previous['quotes'],
                               snapshot['quotes'], shadow_fills, snapshot['actions'])
            rp, rt = economics(previous['actual_holdings'], snapshot['actual_holdings'], previous['quotes'],
                               snapshot['quotes'], snapshot['actual_fills'], snapshot['actions'])
            actual_cost = rp + rt - (real - previous_real)
            shadow_cost = sp + st - (shadow - previous_shadow)
            known_cost = sum(state[k] - observed[i - 1][k] for k in
                             ('interest_paid', 'fees_paid', 'dividend_tax_paid'))
            if abs(shadow_cost - known_cost) > .02:
                raise ValueError(f'{day}: independent shadow cash ledger fails: {shadow_cost} vs {known_cost}')
            difference = (shadow - previous_shadow) - (real - previous_real)
            if abs(difference - ((sp - rp) + (st - rt) + actual_cost - shadow_cost)) > .001:
                raise ValueError('Difference attribution fails')
            attribution.append(dict(date=day, position_and_action_difference=sp - rp,
                                    fill_price_difference=st - rt, actual_unclassified_cost=actual_cost,
                                    shadow_modelled_cost=shadow_cost, cost_difference=actual_cost - shadow_cost,
                                    daily_shadow_minus_actual=difference))
        previous_shadow, previous_real = shadow, real
    return rows, attribution


def load_book(book):
    protocol = json.loads((book / 'protocol.json').read_text())
    if protocol['code_sha256'] != code_hashes() or protocol['base'] != sweep.BASE:
        raise ValueError('Frozen code/BASE changed; review and start a new book instead of rewriting history')
    snapshots = [json.loads(p.read_text()) for p in sorted((book / 'snapshots').glob('*.json'))]
    for s in snapshots:
        path = book / 'snapshots' / f'{s["date"]}.json'
        if sha(path.read_bytes()) != protocol['snapshots'][s['date']]:
            raise ValueError(f'Archived snapshot changed: {s["date"]}')
    dates = [s['date'] for s in snapshots]
    if not dates or dates[0] != protocol['baseline_date'] or len(dates) != len(set(dates)) or \
            set(dates) != set(protocol['snapshots']):
        raise ValueError('Invalid snapshot date sequence')
    if any(s['actual_strategy_epoch'] != protocol['strategy_epoch'] for s in snapshots[1:]):
        raise ValueError('Real strategy epoch changed; start a new comparison book')
    expected = [d for d in snapshots[-1]['available_account_dates'] if dates[0] <= d <= dates[-1]]
    if dates != expected:
        raise ValueError('Missing account dates in shadow archive')
    return protocol, snapshots


def report(book, protocol, snapshots, rows, attribution, fills, observed):
    first, last = rows[0], rows[-1]
    pct = lambda x: f'{x * 100:+.3f}%'
    lines = [f'# {protocol["strategy_epoch"]} 影子组合与实盘对照', '',
             f'基准：{first["date"]}收盘；截至：{last["date"]}；{len(rows)-1}个交易日。', '',
             f'建立时间：{protocol["created_at_beijing"]}。截至{protocol["retrospective_through"]}为历史回放；其后完整交易日才属于前向观察。', '',
             '| 指标 | 影子组合 | 实盘 |', '| --- | ---: | ---: |',
             f'| 初始净资产 | {first["shadow_net_assets"]:,.2f} | {first["actual_net_assets"]:,.2f} |',
             f'| 期末净资产 | {last["shadow_net_assets"]:,.2f} | {last["actual_net_assets"]:,.2f} |',
             f'| 区间累计收益 | {pct(last["shadow_return"])} | {pct(last["actual_return"])} |',
             f'| 区间最大回撤 | {min(r["shadow_drawdown"] for r in rows)*100:.3f}% | {min(r["actual_drawdown"] for r in rows)*100:.3f}% |',
             f'| 期末融资负债 | {last["shadow_debt"]:,.2f} | {last["actual_debt"]:,.2f} |', '',
             f'影子减实盘：**{last["shadow_minus_actual_cny"]:+,.2f}元／{last["shadow_minus_actual_pp"]:+.4f}个百分点**。', '',
             '这是按BASE融资公式独立运行的对照账户。净值接近不等于交易一致；下文分别列出持仓、成交与券商额度差异。', '',
             '## 逐日收益', '', '| 日期 | 影子累计 | 实盘累计 | 影子减实盘（元） |', '| --- | ---: | ---: | ---: |']
    lines += [f'| {r["date"]} | {pct(r["shadow_return"])} | {pct(r["actual_return"])} | {r["shadow_minus_actual_cny"]:+,.2f} |' for r in rows]
    lines += ['', '## 逐笔模拟成交', '', '| 日期 | 方向 | 代码 | 股数 | 收盘模拟价 | 原因 |', '| --- | --- | --- | ---: | ---: | --- |']
    lines += [f'| {r["date"]} | {r["side"]} | {r["security_code"]} | {r["shares"]:,.0f} | {r["price"]:.3f} | {r["reason"]} |' for r in fills]
    lines += ['', '## 差额归因', '', '正数表示增加“影子减实盘”；实盘未分类成本是由账户恒等式倒算的净影响，不能认定为某一费用。', '',
              '| 来源 | 累计影响（元） |', '| --- | ---: |']
    for key, label in [('position_and_action_difference', '持仓与公司行动差异'),
                       ('fill_price_difference', '成交价相对收盘的差异'), ('cost_difference', '成本／未分类账户影响差异')]:
        lines.append(f'| {label} | {sum(r[key] for r in attribution):+,.2f} |')
    lines += ['', f'影子已计费用与利息：{sum(r["shadow_modelled_cost"] for r in attribution):,.2f}元；实盘未分类净影响：{sum(r["actual_unclassified_cost"] for r in attribution):,.2f}元。', '',
              '## 当前持仓差异', '', '| 代码 | 名称 | 影子股数 | 实盘股数 |', '| --- | --- | ---: | ---: |']
    shadow_h, real_h = observed[-1]['holdings'], snapshots[-1]['actual_holdings']
    for c in sorted(shadow_h.keys() | real_h.keys()):
        lines.append(f'| {c} | {snapshots[-1]["quotes"][c]["security_name"]} | {shadow_h.get(c, {}).get("shares", 0):,.0f} | {real_h.get(c, {}).get("shares", 0):,.0f} |')
    lines += ['', '## 资金口径对照', '',
              '本组合是BASE融资规则下的影子组合；券商实际额度没有可重建的反事实算法，因此同时列出实盘报告额度，不能把全部交易差异称为漏执行或超买。', '',
              '| 信号日 | 影子公式可用资金 | 实盘按同式估算 | 实报券商可用资金 |', '| --- | ---: | ---: | ---: |']
    ratio = engine_kwargs(protocol['base'])['credit_ratio']
    for r, s in zip(rows, snapshots):
        shadow_funds = r['shadow_cash'] + ratio * r['shadow_net_assets'] - r['shadow_debt']
        real_funds = s['account']['cash_cny'] + ratio * r['actual_net_assets'] - r['actual_debt']
        reported = s['reported_available_margin']
        reported = f'{reported + s["account"]["cash_cny"]:,.2f}' if reported is not None else '未取得'
        lines.append(f'| {r["date"]} | {shadow_funds:,.2f} | {real_funds:,.2f} | {reported} |')
    discrepancies = [r for s in snapshots for r in s['trade_amount_discrepancies']]
    if discrepancies:
        lines += ['', '## 原记录金额核对', '', '模拟与归因按确认的股数×成交价计算；原始存档保留，不把原记录的乘算差额算作交易费用。', '']
        for r in discrepancies:
            lines.append(f'- {r["date"]} {r["security_code"]}：原金额{r["recorded_amount"]:,.2f}元；股数×价格{r["shares_times_price"]:,.2f}元，原记录多{r["recorded_minus_calculated"]:,.2f}元。')
    lines += ['', '## 口径与限制', '',
              '- 独立继承基准日持仓、成本、止损锚、现金和融资负债；此后不向实盘重置。参数来自冻结BASE，名单、估值、均线、复核冻结和L3闸门来自原信号日存档。',
              '- 按T日信号、T+1收盘价模拟执行，止损按成交日价格与均线判断；收盘价近似不代表14:45–14:55真实可成交价。未跑额外滑点压力测试。',
              '- 影子可用资金按自身净资产与BASE授信规则计算，不能直接复用已经分歧的实盘券商保证金额度；这部分差异不应全归因于人工执行。',
              '- 佣金、最低佣金、印花税、过户费和融资利率来自现行BASE。实盘的实际利率及完整费用明细未齐，不把剩余差额解释为策略收益。',
              '- 初始股份缺少完整FIFO买入与历史红利税批次；未估算建立前已收红利的递延税，未来继承持仓出现公司行动时先停止并补齐批次资料。',
              '- 目前只发布连续账户日期、完整当日持仓报价、零外部出入金且实际成交能够闭合持仓变化的区间；缺失时报错，不静默补零。',
              '- 短期回放用于检查执行和记账，不能据此验证长期盈利能力。', '',
              '证据：`protocol.json`、`snapshots/`、`daily_comparison.csv`、`shadow_fills.csv`、`actual_fills.csv`、`daily_attribution.csv`、`portfolio_states.json`、`verification.json`。', '']
    (book / 'report.md').write_text('\n'.join(lines))


def run_book(book):
    before = real_hashes()
    protocol, snapshots = load_book(book)
    result, observed, fills = simulate(snapshots, protocol)
    rows, attribution = compare(snapshots, result, observed, fills)
    # Validate before publishing any derived output.
    if len(snapshots) > 2:
        prefix, prefix_states, prefix_fills = simulate(snapshots[:-1], protocol)
        if prefix['equity'] != result['equity'][:-1] or prefix_states != observed[:-1] or \
                prefix_fills != [r for r in fills if r['date'] < snapshots[-1]['date']]:
            raise ValueError('Future snapshot changed an earlier decision')
    unchanged = before == real_hashes()
    if not unchanged:
        raise ValueError('Production files changed during shadow replay')
    write_csv(book / 'daily_comparison.csv', rows)
    write_csv(book / 'daily_attribution.csv', attribution, ['date'])
    write_csv(book / 'shadow_fills.csv', fills, ['date', 'security_code', 'side', 'shares', 'price', 'reason'])
    write_csv(book / 'actual_fills.csv', [f for s in snapshots[1:] for f in s['actual_fills']],
              ['date', 'security_code', 'side', 'shares', 'price'])
    write_csv(book / 'shadow_holdings.csv', [dict(security_code=c, **h) for c, h in observed[-1]['holdings'].items()],
              ['security_code', 'shares', 'cost', 'stop', 'stop_ma'])
    save(book / 'portfolio_states.json', observed)
    discrepancies = [r for s in snapshots for r in s['trade_amount_discrepancies']]
    write_csv(book / 'source_amount_discrepancies.csv', discrepancies,
              ['date', 'security_code', 'recorded_amount', 'shares_times_price', 'recorded_minus_calculated', 'source'])
    save(book / 'verification.json', dict(snapshot_hashes_valid=True,
         days=len(rows), inherited_positions=len(snapshots[0]['actual_holdings']),
         shadow_fills=len(fills), real_fills=sum(len(s['actual_fills']) for s in snapshots[1:]),
         account_identities=True, holding_changes_reconciled=True, independent_cash_ledger=True,
         difference_attribution=True, prefix_invariance=len(snapshots)>2,
         shadow_min_cash=min(r['shadow_cash'] for r in rows),
         production_inputs_unchanged=unchanged, production_input_sha256=before,
         source_amount_discrepancies=len(discrepancies)))
    report(book, protocol, snapshots, rows, attribution, fills, observed)
    print(json.dumps(rows[-1], ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'capture', 'run'))
    parser.add_argument('--book', type=Path, default=DEFAULT_BOOK)
    parser.add_argument('--sources', type=Path, help='Initial date -> Git revision JSON map')
    parser.add_argument('--epoch', help='Strategy epoch to freeze (default: last initial snapshot)')
    parser.add_argument('--as-of', help='Completed production signal date for capture')
    args = parser.parse_args()
    book = args.book
    if args.command == 'init':
        if not args.sources or (book.exists() and any(book.iterdir())):
            raise ValueError('init requires --sources and a new book')
        refs = json.loads(args.sources.read_text())
        if not refs:
            raise ValueError('Empty initialization map')
        engine_kwargs(sweep.BASE)
        snapshots = [capture_snapshot(day, Source(revision), sweep.BASE, baseline=day == min(refs))
                     for day, revision in sorted(refs.items())]
        epoch = args.epoch or snapshots[-1]['actual_strategy_epoch']
        if any(s['actual_strategy_epoch'] != epoch for s in snapshots[1:]):
            raise ValueError('Initial comparison crosses strategy epochs')
        expected = [d for d in snapshots[-1]['available_account_dates'] if min(refs) <= d <= max(refs)]
        if sorted(refs) != expected:
            raise ValueError('Missing account dates in initialization')
        protocol = dict(schema=1, created_at_beijing=now(), baseline_date=min(refs),
                        retrospective_through=max(refs), base=sweep.BASE,
                        strategy_epoch=epoch,
                        fees=dict(bt.USER_FEES, stamp_mode='flat'), code_sha256=code_hashes(), snapshots={})
        for snapshot in snapshots:
            day = snapshot['date']
            path = book / 'snapshots' / f'{day}.json'
            save(path, snapshot)
            protocol['snapshots'][day] = sha(path.read_bytes())
        save(book / 'protocol.json', protocol)
        print(f'Initialized {book}; run separately to calculate results')
    elif args.command == 'capture':
        protocol, snapshots = load_book(book)
        if not args.as_of or args.as_of <= snapshots[-1]['date']:
            raise ValueError('Capture must append a new, completed signal date')
        publication = json.loads((ROOT / 'data/processed/daily_execution_publication.json').read_text())
        if publication.get('status') != 'complete' or publication.get('as_of') != args.as_of:
            raise ValueError('Production publication incomplete or dated differently')
        snapshot = capture_snapshot(args.as_of, Source(), protocol['base'])
        if snapshot['actual_strategy_epoch'] != protocol['strategy_epoch']:
            raise ValueError('Real strategy epoch changed; start a new comparison book')
        expected = [d for d in snapshot['available_account_dates'] if d > snapshots[-1]['date']]
        if expected != [args.as_of]:
            raise ValueError('Intervening account dates must be archived first')
        path = book / 'snapshots' / f'{args.as_of}.json'
        if path.exists():
            raise ValueError('Refusing to overwrite an archived snapshot')
        # Validate the full new path before accepting this snapshot.
        result, observed, fills = simulate(snapshots + [snapshot], protocol)
        compare(snapshots + [snapshot], result, observed, fills)
        save(path, snapshot)
        protocol['snapshots'][args.as_of] = sha(path.read_bytes())
        save(book / 'protocol.json', protocol)
        print(f'Archived {args.as_of}')
    else:
        run_book(book)


if __name__ == '__main__':
    main()

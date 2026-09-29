"""OI-239 研究开关：在 OI-238 补丁（`../exp_oi238_20260930/patch.py`，其下依次是 OI-236、OI-235、OI-233 补丁）之上再加内存补丁，
不改 `scripts/backtest_valuation_strategy.py`（影子组合按其指纹冻结）。开关缺省全关时与 OI-238 补丁引擎逐位相同。

* `--t-drop θ [--t-window W] [--t-cost adjust|std]`（做 T）：
  - 登记：每笔盈利偏离让位减仓记（减仓价 P_s、所减股数 q、减仓日 d0、受让股 X、减仓时持仓均价 C）。
  - 触发：d0 之后 W 个交易日内，某日尾盘收盘 ≤ P_s ×(1−θ)（执行时点价，同 OI-235 买回口径），每只每日至多一笔，先到期先做。
  - 资金：从近 W 个交易日内（不含当日，A 股 T+1）买入、当日收盘不低于买入价（没亏）的持仓里取一只卖出，
    该笔让位的受让股（d0 及以后买入）优先，其余按最近买入在先；只卖够买回所需的手数（上限为那笔近期买入的股数）。
    负债超出授信额度的日子不做（§10.2 先还后买）。
  - 买回：排在当日买入段队首，买回 min(q, 卖出所得) 的整手，不过买入线与走势判据（用户规则未设）。
  - 成本：`adjust`（用户口径）买回部分的成本按「减仓时均价 C − 本次 T 的每股差价 (P_s − 买回价)」计入，
    即持仓均价 = (原持股 × 原均价 + 买回股数 × (C − (P_s − 买回价))) ÷ 合计股数；`std` 按引擎常规加权（对照）。
* 返回值增 `t_log`（做 T 流水）。

    from patch import load
    bt = load()
"""
import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('patch238', HERE.parent / 'exp_oi238_20260930' / 'patch.py')
patch238 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch238)
SRC = patch238.SRC

PATCHES = [
    # 1. run() 参数
    ('''        nh_mode: str | None = None, nh_highs: dict | None = None, nh_gain: bool = False,
''',
     '''        nh_mode: str | None = None, nh_highs: dict | None = None, nh_gain: bool = False,
        t_drop: float = 0.0, t_window: int = 5, t_cost: str = "adjust",
'''),
    # 2. 状态
    ('''    nh_log: list = []               # OI-238：被「创新高」挡下的（类别, 代码, 减仓日）
''',
     '''    nh_log: list = []               # OI-238：被「创新高」挡下的（类别, 代码, 减仓日）
    t_pending: dict = {}            # OI-239：代码 → [[减仓价, 所减股数, 到期 day_no, 减仓日, 受让股, 减仓时均价], ...]
    t_buys: list = []               # OI-239：近期买入 [day_no, 日, 代码, 可作资金来源的剩余股数, 买入价]
    t_rebuy_today: dict = {}        # OI-239：当日做 T 买回的代码 → (记录, 卖出股, 卖出股数, 卖出价, 其买入价, 日)
    t_sold_today: set = set()       # OI-239：当日为做 T 卖出的资金来源（当日不再常规买入）
    t_log: list = []                # OI-239：做 T 流水
'''),
    # 3. 除权：待做 T 与近期买入按 §11.4 同式折算
    ('''        if bb_pending:                                            # OI-235 B：待买回的价与股数按 §11.4 同式折算
''',
     '''        if t_drop and (t_pending or t_buys):                       # OI-239：待做 T 与近期买入按 §11.4 同式折算
            from corporate_actions import price_terms as _pt239
            for _c in set(t_pending) | {_b[2] for _b in t_buys}:
                _ev = actions.get(_c, {}).get(day)
                if not _ev:
                    continue
                _pc, _pr, _prr, _prp = _pt239(_ev)
                _den = 1.0 + _pr + _prr
                _adj = lambda x: ((x + _prr * _prp - _pc) / _den) if x + _prr * _prp - _pc > 0 else x / _den
                for _rec in t_pending.get(_c, []):
                    _rec[0], _rec[1], _rec[5] = _adj(_rec[0]), _rec[1] * _den, (_adj(_rec[5]) if _rec[5] > 0 else _rec[5])
                for _b in t_buys:
                    if _b[2] == _c:
                        _b[4], _b[3] = _adj(_b[4]), _b[3] * _den
        if bb_pending:                                            # OI-235 B：待买回的价与股数按 §11.4 同式折算
'''),
    # 4. 登记待做 T
    ('''                    bb_log.append(("trim", worst, day, price, sold_qty))
''',
     '''                    bb_log.append(("trim", worst, day, price, sold_qty))
                    if t_drop:                                   # OI-239：登记待做 T
                        t_pending.setdefault(worst, []).append([sp, sold_qty, day_no + t_window, day, code, lot_worst.avg_cost])
'''),
    # 5. 做 T：卖出近期买入且没亏的一只，买回排在买入段队首
    ('''            buy_plan = _front + buy_plan
''',
     '''            buy_plan = _front + buy_plan
        if t_rebuy_today:                                          # OI-239：前一日卖了资金来源却没买回
            stats["做T·卖出后未买回"] += len(t_rebuy_today)
            t_log.extend(("miss", _a, _v[0][3], _v[1], _v[5]) for _a, _v in t_rebuy_today.items())
            t_rebuy_today.clear()
        t_sold_today.clear()
        if t_drop:
            t_buys[:] = [_b for _b in t_buys if _b[0] >= day_no - t_window and _b[3] > 1e-9]
        if t_drop and t_pending:
            _front_t = []
            _over = credit_over_limit == "repay" and credit_ratio > 0 and portfolio.debt > credit_limit + 1e-6
            for _a in sorted(t_pending):
                _recs = [_r for _r in t_pending[_a] if _r[2] >= day_no and _r[1] > 1e-9]
                if not _recs:
                    t_pending.pop(_a)
                    continue
                t_pending[_a] = _recs
                _apx = prices.get(_a, {}).get(day)
                if not _apx or _a not in today or (members is not None and _a not in members):
                    continue
                _hit = [_r for _r in _recs if _r[3] < day and _apx <= _r[0] * (1.0 - t_drop)]
                if not _hit:
                    continue
                _rec = _hit[0]
                stats["做T·触发"] += 1
                if (net_reg and _a in net_reg) or _a in reduced_today or _a in swap_sources_today:
                    stats["做T·当日已减仓跳过"] += 1                 # 同日又被减仓：不做 T（否则买回与当日卖出对冲）
                    continue
                if _over:
                    stats["做T·超额授信跳过"] += 1
                    continue
                _need = _rec[1] * px_buy(_apx)
                _cands = []
                for _b in reversed(t_buys):
                    if (_b[3] <= 1e-9 or _b[2] == _a or _b[1] >= day or _b[2] not in portfolio.lots
                            or (members is not None and _b[2] not in members)):
                        continue
                    _xpx = prices.get(_b[2], {}).get(day)
                    if not _xpx or _xpx < _b[4] or _b[2] in t_rebuy_today:
                        continue
                    _cands.append(((_b[2] != _rec[4] or _b[1] < _rec[3]), _b, _xpx))
                if not _cands:
                    stats["做T·无没亏的近期买入"] += 1
                    continue
                _prio, _b, _xpx = min(_cands, key=lambda z: z[0])
                _x = _b[2]
                _xl = portfolio.lots[_x]
                _xsp = px_sell(_xpx)
                _want = (min(_b[3], _xl.shares, -(-_need // (_xsp * lot_size)) * lot_size) if lot_size
                         else min(_b[3], _xl.shares, _need / _xsp))
                _xs = sell_shares(_want, _xl.shares, _xsp, lot_size, res_floor(_xsp), residual_clear_cny)
                if _xs <= 0:
                    stats["做T·近期买入不足一手"] += 1
                    continue
                _cash0 = portfolio.cash
                _reason = f"做T·卖出近期买入：买回{_a}"
                if _xs < _xl.shares * 0.999:
                    _xl.shares -= _xs
                    _consumed = []
                    portfolio.cash -= sell_dividend_tax(portfolio, _xl, _xs, day, _consumed)
                    portfolio.cash += _xs * _xsp - trade_fee(_xs * _xsp, day, "sell")
                    _xl.proceeds += _xs * _xsp
                    _xl.sells += 1
                    log_partial_sell(ledger, day, _x, _xs, _xsp, _reason)
                    register_sale(net_reg, _x, _xl, _xs, _xsp, _consumed, False, None,
                                  (len(ledger) - 1) if ledger is not None else None, False)
                else:
                    _xs = _xl.shares
                    close_lot(portfolio, _x, day, _xsp, ledger=ledger, reason=_reason, net_reg=net_reg)
                turnover += _xs * _xsp
                sell_count += 1
                stats["做T·卖出资金来源" + ("·受让股" if not _prio else "·其他近期买入")] += 1
                _b[3] -= min(_b[3], _xs)
                t_sold_today.add(_x)
                _front_t.append(((_a, *today[_a]), max(0.0, min(_need, portfolio.cash - _cash0))))
                t_rebuy_today[_a] = (_rec, _x, _xs, _xsp, _b[4], day)
                _rec[1] = 0.0
            buy_plan = _front_t + buy_plan
'''),
    # 6a. 买入段：做 T 卖出的资金来源当日不再常规买入（否则与做 T 卖出同日对冲）
    ('''        for (code, close, value, ratio), pair_amount in buy_plan:
            if confirmed_cooldown and not cooldown_buy.ready(code):
''',
     '''        for (code, close, value, ratio), pair_amount in buy_plan:
            if t_sold_today and code in t_sold_today and pair_amount is None:   # OI-239：做 T 刚卖出的资金来源当日不再买入
                stats["做T·卖出股当日不再买入"] += 1
                continue
            if confirmed_cooldown and not cooldown_buy.ready(code):
'''),
    # 6. 买入后：登记近期买入；做 T 买回更新成本
    ('''            if pair_amount is not None and code in bb_hit_today:  # OI-235 B：核销买回（先到期先核销）
''',
     '''            if t_drop:                                             # OI-239：登记近期买入；做 T 买回更新成本
                t_buys.append([day_no, day, code, shares, bp])
                if pair_amount is not None and code in t_rebuy_today:
                    _rec, _x, _xs, _xsp, _xbp, _d = t_rebuy_today.pop(code)
                    _s0 = lot.shares - shares
                    _c0 = (lot.avg_cost * lot.shares - amount) / _s0 if _s0 > 1e-9 else 0.0
                    _avg_std = lot.avg_cost
                    if t_cost == "adjust":
                        lot.avg_cost = max(1e-6, (_s0 * _c0 + shares * (_rec[5] - (_rec[0] - bp))) / (_s0 + shares))
                    t_log.append(("T", code, _rec[3], _rec[0], day, bp, shares, _x, _xs, _xsp, _xbp, _rec[5], _avg_std, lot.avg_cost,
                                  ratio))
                    stats["做T·买回"] += 1
            if pair_amount is not None and code in bb_hit_today:  # OI-235 B：核销买回（先到期先核销）
'''),
    # 7. 返回值
    ('''"vd_log": vd_log, "nh_log": nh_log, "buys": buy_count,''',
     '''"vd_log": vd_log, "nh_log": nh_log, "t_log": t_log, "buys": buy_count,'''),
    # 8. 命令行与传参
    ('''    parser.add_argument("--nh-gain", action="store_true", help="研究开关（OI-238）：涨幅减持同样要求未创新高")
''',
     '''    parser.add_argument("--nh-gain", action="store_true", help="研究开关（OI-238）：涨幅减持同样要求未创新高")
    parser.add_argument("--t-drop", type=float, default=0.0,
                        help="研究开关（OI-239）：让位减仓后 W 日内收盘 ≤ 减仓价×(1−θ) 即卖出近期买入且没亏的一只、买回所减股数；0=关")
    parser.add_argument("--t-window", type=int, default=5, help="研究开关（OI-239）：做 T 窗口与「近期买入」窗口（交易日）")
    parser.add_argument("--t-cost", choices=("adjust", "std"), default="adjust",
                        help="研究开关（OI-239）：买回部分成本按减仓时均价扣减做 T 差价（adjust，用户口径）或常规加权（std）")
'''),
    ('''                         nh_mode=args.nh_trim, nh_highs=nh_highs, nh_gain=args.nh_gain,
''',
     '''                         nh_mode=args.nh_trim, nh_highs=nh_highs, nh_gain=args.nh_gain,
                         t_drop=args.t_drop, t_window=args.t_window, t_cost=args.t_cost,
'''),
]


def patched_source() -> str:
    text = patch238.patched_source()
    for old, new in PATCHES:
        assert text.count(old) == 1, ('patch anchor not unique', old[:90])
        text = text.replace(old, new)
    return text


def load():
    if str(SRC.parent) not in sys.path:
        sys.path.insert(0, str(SRC.parent))
    mod = types.ModuleType('backtest_valuation_strategy')
    mod.__file__ = str(SRC)
    sys.modules['backtest_valuation_strategy'] = mod
    exec(compile(patched_source(), str(SRC), 'exec'), mod.__dict__)
    return mod

"""OI-235 研究开关：在 OI-233 补丁（`../exp_oi233_20260929/patch.py`，BT／ZH）之上再加内存补丁，不改
`scripts/backtest_valuation_strategy.py`（影子组合按其指纹冻结）。开关缺省全关时与 OI-233 补丁后的引擎逐位相同。

* `--add-bt`（A）：已持仓加仓改按建仓条件（与 `--bt-quiet K` 同一判据：近 K 日最低价未创 20 日新低、收盘 > MA5 与 MA20），
  不再要求 MA20 > MA60；须与 `--bt-quiet` 同用。一档大小用现有 `--x`（买入）与 `--sell-x`（卖出）。
* `--swap-ext G D20 D5`（B）：换仓卖出源改为「信号日收盘 ≥ 持仓均价 ×(1+G)，且 ≥ MA20 ×(1+D20)、≥ MA5 ×(1+D5)」
  （D 为 0 即不要求该条），取收盘 ÷ MA20 最大者减一档；取代「收盘 < MA20 的最贵持仓 + P/V 边际」一路，
  涨幅减持源（≥ 110%）一路照旧优先。
* `--swap-bb N B`（B）：上一路让位减仓后 N 个交易日内，执行时点价（以收盘代）≤ 减仓价 ×(1−B) 即按所减股数买回，
  排在当日买入队首，资金、整手、单票上限、股债上限照常；到期未触发即作废。待买回的价与股数按 §11.4 同式除权折算。
* `--value-sell-ungated`（C）：`--sell-line` 触发的估值减持不过走势闸门（现行 `--sell-trend-ma 20` 要求收盘 < MA20）。
* `--value-sell-full`（C）：`--sell-line` 触发即整仓卖出（涨幅减持仍按一档）。

    from patch import load
    bt = load()          # 返回已打补丁的模块，并登记为 sys.modules['backtest_valuation_strategy']
"""
import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('patch233', HERE.parent / 'exp_oi233_20260929' / 'patch.py')
patch233 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch233)
SRC = patch233.SRC
EXT_TAG = '·盈利偏离让位'

PATCHES = [
    # 1. run() 参数
    ('''        zone_hold_pv: float = 0.0, bt_quiet: int = 0, bt_lows: dict | None = None,
''',
     '''        zone_hold_pv: float = 0.0, bt_quiet: int = 0, bt_lows: dict | None = None,
        add_bt: bool = False, swap_ext: tuple | None = None, swap_bb: tuple | None = None,
        value_sell_ungated: bool = False, value_sell_full: bool = False,
'''),
    # 2. 逐日循环外的状态
    ('''    contrib: dict[str, float] = collections.defaultdict(float)
''',
     '''    contrib: dict[str, float] = collections.defaultdict(float)
    bb_pending: dict = {}           # OI-235 B：代码 → [[减仓价, 待买回股数, 到期 day_no, 减仓日], ...]
    bb_hit_today: dict = {}         # OI-235 B：当日触发买回的代码 → 触发的待买回记录
    bb_log: list = []               # OI-235 B：让位减仓与买回流水
'''),
    # 3. 待买回记录的除权折算（§11.4 同式）
    ('''        apply_corporate_actions(portfolio, day, actions, adjust_stops=(exright_stop == "adjust"))
''',
     '''        apply_corporate_actions(portfolio, day, actions, adjust_stops=(exright_stop == "adjust"))
        if bb_pending:                                            # OI-235 B：待买回的价与股数按 §11.4 同式折算
            from corporate_actions import price_terms as _price_terms
            for _c, _recs in bb_pending.items():
                _ev = actions.get(_c, {}).get(day)
                if not _ev:
                    continue
                _pc, _pr, _prr, _prp = _price_terms(_ev)
                for _rec in _recs:
                    _adj = (_rec[0] + _prr * _prp - _pc) / (1.0 + _pr + _prr)
                    _rec[0] = _adj if _adj > 0 else _rec[0] / (1.0 + _pr + _prr)
                    _rec[1] *= 1.0 + _ev[1] + _ev[2]
'''),
    # 4. A：已持仓加仓同建仓条件
    ('''                if bt_quiet and r[0] not in portfolio.lots:      # OI-233 BT：新建仓改按前低企稳＋站上 MA5／MA20
                    return _bt_ok(r[0], buy_day, r[1])
''',
     '''                if bt_quiet and r[0] not in portfolio.lots:      # OI-233 BT：新建仓改按前低企稳＋站上 MA5／MA20
                    return _bt_ok(r[0], buy_day, r[1])
                if add_bt and bt_quiet and r[0] in portfolio.lots and r[0] not in left_topup:
                    return _bt_ok(r[0], buy_day, r[1])           # OI-235 A：加仓同建仓条件，不要求 MA20 > MA60
'''),
    # 5. B：盈利＋偏离让位源
    ('''                swap_tag = ""
                if gain_src:
''',
     '''                swap_tag = ""
                ext_src = []
                if swap_ext and not gain_src:                    # OI-235 B：盈利 ≥ G 且收盘偏离 MA20／MA5 达 D 的持仓让位
                    _g, _d20, _d5 = swap_ext
                    for c, l in portfolio.lots.items():
                        if (c not in today or c == code or l.avg_cost <= 0 or c in quota_hold_today
                                or (execution_consistency == "signal" and c in outlist_sold_today)
                                or c in reduced_today or (swap_gain_once and c in gain_trimmed_today)):
                            continue
                        _cl = src_close(c)
                        _mx = mas.get(c, {}).get(src_ma_day, {})
                        if not _cl or _cl < l.avg_cost * (1.0 + _g) or not _mx.get(20):
                            continue
                        if _d20 and _cl < _mx[20] * (1.0 + _d20):
                            continue
                        if _d5 and not (_mx.get(5) and _cl >= _mx[5] * (1.0 + _d5)):
                            continue
                        ext_src.append((_cl / _mx[20], _cl / l.avg_cost, c))
                if gain_src:
'''),
    ('''                else:
                    if not held:
                        break
                    worst_ratio, worst = max(held)
''',
     '''                elif swap_ext:
                    if not ext_src:
                        break
                    worst = max(ext_src)[2]
                    swap_tag = "''' + EXT_TAG + '''"
                    stats["盈利偏离·换仓让位"] += 1
                else:
                    if not held:
                        break
                    worst_ratio, worst = max(held)
'''),
    # 6. B：登记让位减仓与待买回
    ('''                swap_sources_today.add(worst)
''',
     '''                swap_sources_today.add(worst)
                if swap_tag == "''' + EXT_TAG + '''" and sold_qty > 0:      # OI-235 B：让位流水与待买回
                    bb_log.append(("trim", worst, day, price, sold_qty))
                    if swap_bb:
                        bb_pending.setdefault(worst, []).append([price, sold_qty, day_no + int(swap_bb[0]), day])
'''),
    # 7. B：买回排在当日买入队首
    ('''        buy_plan = ([(r, pair_alloc[r[0]]) for r in eligible[:max_positions] if pair_alloc.get(r[0], 0.0) > 0]
                    + ([(r, None) for r in eligible[:max_positions]] if pair_regular else []))
''',
     '''        buy_plan = ([(r, pair_alloc[r[0]]) for r in eligible[:max_positions] if pair_alloc.get(r[0], 0.0) > 0]
                    + ([(r, None) for r in eligible[:max_positions]] if pair_regular else []))
        bb_hit_today.clear()
        if bb_pending:                                            # OI-235 B：执行时点价 ≤ 减仓价 ×(1−B) 即买回所减股数
            _front = []
            for _c in sorted(bb_pending):
                _recs = [_r for _r in bb_pending[_c] if _r[2] >= day_no and _r[1] > 1e-9]
                if not _recs:
                    bb_pending.pop(_c)
                    continue
                bb_pending[_c] = _recs
                _px = prices.get(_c, {}).get(day)
                if not _px or _c not in today or (members is not None and _c not in members):
                    continue
                _hit = [_r for _r in _recs if _r[3] < day and _px <= _r[0] * (1.0 - swap_bb[1])]
                if _hit:
                    bb_hit_today[_c] = _hit
                    _front.append(((_c, *today[_c]), sum(_r[1] for _r in _hit) * px_buy(_px)))
            buy_plan = _front + buy_plan
'''),
    ('''            last_buy[code] = day
''',
     '''            last_buy[code] = day
            if pair_amount is not None and code in bb_hit_today:  # OI-235 B：核销买回（先到期先核销）
                _left = shares
                for _r in sorted(bb_hit_today.pop(code), key=lambda z: z[2]):
                    _take = min(_r[1], _left)
                    if _take > 0:
                        bb_log.append(("match", code, _r[3], _r[0], _take, day, bp))
                    _r[1] -= _take
                    _left -= _take
                bb_log.append(("buyback", code, day, bp, shares))
                stats["做T·买回"] += 1
'''),
    # 8. C：估值减持不过走势闸门；过线整仓卖出
    ('''            if sell_trend_ma and not (gain_hit and gain_sell_mode == "ungated"):
''',
     '''            if sell_trend_ma and not (gain_hit and gain_sell_mode == "ungated") and not (value_rich and value_sell_ungated):
'''),
    ('''            if value_rich or gain_hit:
                if confirmed_cooldown and not cooldown_sell.ready(code):
                    continue
                cooldown_proceeds = lot.proceeds
''',
     '''            if value_rich or gain_hit:
                if confirmed_cooldown and not cooldown_sell.ready(code):
                    continue
                cooldown_proceeds = lot.proceeds
                if value_rich and value_sell_full:                # OI-235 C：P/V 过线整仓卖出
                    stats["P/V过线·整仓卖出"] += 1
                    turnover += lot.shares * sp
                    close_lot(portfolio, code, day, sp, ledger=ledger, reason=f"{rich_tag}整仓卖出")
                    sell_count += 1
                    continue
'''),
    # 9. 返回值带让位／买回流水
    ('''"contrib": dict(contrib), "buys": buy_count,''',
     '''"contrib": dict(contrib), "bb_log": bb_log, "buys": buy_count,'''),
    # 10. 命令行与传参
    ('''                        help="研究开关（OI-233 BT）：新建仓 = 近 K 日最低价未创 20 日新低且收盘 > MA5、> MA20，锚 = 信号日 20 日最低价；0=关")
''',
     '''                        help="研究开关（OI-233 BT）：新建仓 = 近 K 日最低价未创 20 日新低且收盘 > MA5、> MA20，锚 = 信号日 20 日最低价；0=关")
    parser.add_argument("--add-bt", action="store_true", help="研究开关（OI-235 A）：已持仓加仓改按建仓条件（须与 --bt-quiet 同用）")
    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
                        help="研究开关（OI-235 B）：换仓卖出源 = 收盘 ≥ 均价×(1+G) 且 ≥ MA20×(1+D20)、≥ MA5×(1+D5)（0=不要求），取代弱势＋P/V 边际")
    parser.add_argument("--swap-bb", type=float, nargs=2, default=None, metavar=("N", "B"),
                        help="研究开关（OI-235 B）：盈利偏离让位后 N 个交易日内执行时点价 ≤ 减仓价×(1−B) 即买回所减股数")
    parser.add_argument("--value-sell-ungated", action="store_true", help="研究开关（OI-235 C）：--sell-line 减持不过走势闸门")
    parser.add_argument("--value-sell-full", action="store_true", help="研究开关（OI-235 C）：--sell-line 触发即整仓卖出")
'''),
    ('''                         zone_hold_pv=args.zone_hold_pv, bt_quiet=args.bt_quiet, bt_lows=bt_lows,
''',
     '''                         zone_hold_pv=args.zone_hold_pv, bt_quiet=args.bt_quiet, bt_lows=bt_lows,
                         add_bt=args.add_bt, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
                         swap_bb=tuple(args.swap_bb) if args.swap_bb else None,
                         value_sell_ungated=args.value_sell_ungated, value_sell_full=args.value_sell_full,
'''),
]


def patched_source() -> str:
    text = patch233.patched_source()
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

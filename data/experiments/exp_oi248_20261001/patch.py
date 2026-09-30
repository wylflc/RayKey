"""OI-248 研究开关：在内存中给原生回测引擎打补丁，不改 `scripts/backtest_valuation_strategy.py`。
开关缺省全关时与原生引擎逐位相同。

规则一（只给盈利仓加仓，AG 臂）：
* `--add-gate M`：已持仓加仓另须信号日收盘 > 持仓均价 × (1 + M)。

规则二（回落撤回加仓，AB／ABM／AX 臂）：
* `--ab-drop D`：本周期有过加仓（买入笔数 ≥ 2）且信号日收盘 < 持仓均价 × (1 − D) 时，成交日卖到只留一档
  （信号日净资产 × `--ab-keep`，按手向下取整，不足一手清仓）；持仓已不超过一档的不动。
* `--ab-ma`：另须信号日 `MA20 ≤ MA60`。
* `--ab-clear`：清仓（对照）。
* 撤回后锁定：本周期加仓须等信号日收盘回到持仓均价以上（解锁）；锁定期间不再触发，解锁后可再次触发。

    from patch import load
    bt = load()          # 返回已打补丁的模块，并登记为 sys.modules['backtest_valuation_strategy']
    bt.AG_LOG, bt.AB_LOG # 本次 run 的加仓闸挡下（信号日, 代码）与撤回（成交日, 代码, 撤回前市值, 卖出额, 均价, 是否清仓）
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / 'scripts' / 'backtest_valuation_strategy.py'

PATCHES = [
    # 1. run() 参数
    ('''        bt_quiet: int = 0, bt_lows: dict | None = None, swap_ext: tuple | None = None,
''',
     '''        bt_quiet: int = 0, bt_lows: dict | None = None, swap_ext: tuple | None = None,
        add_gate: float | None = None, ab_drop: float | None = None, ab_ma: bool = False, ab_clear: bool = False,
        ab_keep: float = 0.05, ag_log: list | None = None, ab_log: list | None = None,
'''),
    # 2. 周期字段：撤回后的加仓锁
    ('''    exit_reason: str = ""
''',
     '''    exit_reason: str = ""
    ab_lock: bool = False       # OI-248：撤回加仓后锁定加仓，信号日收盘回到均价以上解锁
'''),
    # 3. 加仓判定：锁定与加仓闸
    ('''                if addon_trend == "ma-only" and r[0] in portfolio.lots and r[0] not in left_topup:
                    return True                      # 已持仓：只看均线排列，不看价格位置
''',
     '''                if addon_trend == "ma-only" and r[0] in portfolio.lots and r[0] not in left_topup:
                    _lt = portfolio.lots[r[0]]
                    if _lt.ab_lock:                                  # OI-248：撤回加仓后锁定
                        stats["撤回加仓·锁定中不加"] += 1
                        return False
                    if add_gate is not None and _lt.avg_cost > 0 and not r[1] > _lt.avg_cost * (1 + add_gate):
                        stats["加仓闸·挡下"] += 1                    # OI-248：只给盈利仓加仓
                        if ag_log is not None:
                            ag_log.append((buy_day, r[0]))
                        return False
                    return True                      # 已持仓：只看均线排列，不看价格位置
'''),
    # 4. 回落撤回加仓（出名单之后、其余退出之前）
    ('''            # 走势退出：**跟随均线**而非建仓日固定价。''',
     '''            if ab_drop is not None:                                  # OI-248：加仓后回落撤回加仓
                _sc = today.get(code, (None,))[0]
                if lot.ab_lock and _sc and lot.avg_cost > 0 and _sc >= lot.avg_cost:
                    lot.ab_lock = False
                    stats["撤回加仓·解锁"] += 1
                _m = mas.get(code, {}).get(sig_day) or {}
                if (_sc and not lot.ab_lock and lot.buys >= 2 and lot.avg_cost > 0 and _sc < lot.avg_cost * (1 - ab_drop)
                        and (not ab_ma or (20 in _m and 60 in _m and _m[20] <= _m[60]))):
                    _keep_val = 0.0 if ab_clear else tranche_equity * ab_keep
                    if lot.shares * sp > _keep_val + 1e-6:
                        _keep = int(_keep_val / sp / lot_size) * lot_size if lot_size else _keep_val / sp
                        _sell = lot.shares - _keep
                        _why = "加仓后回落·" + ("清仓" if ab_clear else "撤回加仓")
                        _full = _keep <= 0 or _sell >= lot.shares * 0.999
                        if ab_log is not None:
                            ab_log.append((day, code, round(lot.shares * sp, 2), round((lot.shares if _full else _sell) * sp, 2),
                                           round(lot.avg_cost, 6), int(_full)))
                        if _full:
                            turnover += lot.shares * sp
                            close_lot(portfolio, code, day, sp, ledger=ledger, reason=_why)
                            sell_count += 1
                            stats["撤回加仓·清仓"] += 1
                            continue
                        log_partial_sell(ledger, day, code, _sell, sp, _why)
                        lot.shares -= _sell
                        portfolio.cash -= sell_dividend_tax(portfolio, lot, _sell, day)
                        portfolio.cash += _sell * sp - trade_fee(_sell * sp, day, "sell")
                        lot.proceeds += _sell * sp
                        lot.sells += 1
                        turnover += _sell * sp
                        sell_count += 1
                        lot.ab_lock = True
                        stats["撤回加仓·减仓"] += 1
            # 走势退出：**跟随均线**而非建仓日固定价。'''),
    # 5. 逐日持仓快照另记买入笔数与锁定
    ('''                                  stop_ma=p.entry_stop_ma) for c, p in portfolio.lots.items()},
''',
     '''                                  stop_ma=p.entry_stop_ma, buys=p.buys, lock=p.ab_lock) for c, p in portfolio.lots.items()},
'''),
    # 6. 记录
    ('''def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
''',
     '''AG_LOG: list = []
AB_LOG: list = []


def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
'''),
    # 7. 命令行与传参
    ('''    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
''',
     '''    parser.add_argument("--add-gate", type=float, default=None, help="研究开关（OI-248）：加仓另须信号日收盘 > 均价 ×(1+M)")
    parser.add_argument("--ab-drop", type=float, default=None, help="研究开关（OI-248）：加仓过且收盘 < 均价 ×(1−D) 时撤回加仓")
    parser.add_argument("--ab-ma", action="store_true", help="研究开关（OI-248）：撤回另须 MA20 ≤ MA60")
    parser.add_argument("--ab-clear", action="store_true", help="研究开关（OI-248）：撤回改为清仓（对照）")
    parser.add_argument("--ab-keep", type=float, default=0.05, help="研究开关（OI-248）：撤回后留的净资产比例（缺省一档 5%%）")
    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
'''),
    ('''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
''',
     '''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
                         add_gate=args.add_gate, ab_drop=args.ab_drop, ab_ma=args.ab_ma, ab_clear=args.ab_clear,
                         ab_keep=args.ab_keep, ag_log=AG_LOG, ab_log=AB_LOG,
'''),
]


def patched_source() -> str:
    text = SRC.read_text(encoding='utf-8')
    for old, new in PATCHES:
        assert text.count(old) == 1, ('patch anchor not unique', text.count(old), old[:90])
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

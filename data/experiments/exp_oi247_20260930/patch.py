"""OI-247 研究开关：在内存中给原生回测引擎打补丁，不改 `scripts/backtest_valuation_strategy.py`。
开关缺省全关时与原生引擎逐位相同。

方案一（前低止损，须去掉 BASE 的 `--no-trend-stop`，沿用 `--bt-quiet` 的建仓锚机制）：
* `--bt-stop-window L`／`--bt-stop-col {low,close}`：建仓锚改取信号日（含）前 L 日的全天最低或收盘最低（缺省 20／low，即原 BT 锚）。
* `--bt-stop-release`：建仓后任一信号日 `MA20 > MA60`，本周期前低止损永久解除。
* `--bt-no-anchor-nostop`：锚缺失的新建仓不设止损（原引擎退回 MA60 锚）。

方案二（长期水下减仓）：
* `--loss-age-days M --loss-age-keep X`：逐信号日收盘低于持仓均价即水下天数 +1、收盘 ≥ 均价即归零（成交日为除权日时不计不归零）；
  满 M 日时持仓市值高于信号日净资产 X 的减到不超过 X（按手向下取整，不足一手清仓），同一段水下只减一次；
  水下天数 ≥ M 期间加仓以 X 为上限。

    from patch import load
    bt = load()          # 返回已打补丁的模块，并登记为 sys.modules['backtest_valuation_strategy']
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
        bt_anchor: dict | None = None, bt_release: bool = False, bt_no_anchor_nostop: bool = False,
        loss_age_days: int = 0, loss_age_keep: float = 0.0,
'''),
    # 2. 周期字段：水下天数与本段已减标记
    ('''    exit_reason: str = ""
''',
     '''    exit_reason: str = ""
    uw_streak: int = 0          # OI-247：连续水下（信号日收盘 < 持仓均价）天数
    uw_trimmed: bool = False    # OI-247：本段水下已减过
'''),
    # 3. 建仓锚改读方案一的锚序列
    ('''        """OI-233 BT：信号日 20 日最低价（末日口径）折回成交日口径；成交日无行情时按信号日口径。"""
        rec = (bt_lows or {}).get(code)
''',
     '''        """OI-233 BT：信号日 20 日最低价（末日口径）折回成交日口径；成交日无行情时按信号日口径。"""
        rec = (bt_anchor if bt_anchor is not None else (bt_lows or {})).get(code)   # OI-247：可换窗口与口径
'''),
    # 4. 锚缺失不设止损
    ('''                    else:
                        stats["前低建仓·无锚沿用MA60"] += 1
''',
     '''                    else:
                        stats["前低建仓·无锚沿用MA60"] += 1
                        if bt_no_anchor_nostop:                   # OI-247：锚缺失不设止损
                            lot.entry_stop, lot.entry_stop_ma = 0.0, 0
                            stats["前低建仓·无锚不设止损"] += 1
'''),
    # 5. 走强解除（在取成交价之前，停牌日同样判）
    ('''                if (outlist and sig_close) or (sig_gain and gain_sell_mode == "ungated"):
                    cooldown_sell.ready(code)
            price = fill_price(code, marks.get(code))
''',
     '''                if (outlist and sig_close) or (sig_gain and gain_sell_mode == "ungated"):
                    cooldown_sell.ready(code)
            if bt_release and lot.entry_stop and not lot.entry_stop_ma:
                _m = mas.get(code, {}).get(sig_day) or {}
                if 20 in _m and 60 in _m and _m[20] > _m[60]:          # OI-247：走到 MA20 > MA60，前低止损永久解除
                    lot.entry_stop = 0.0
                    stats["前低止损·走强解除"] += 1
            if loss_age_days and day not in actions.get(code, {}):
                _sc = today.get(code, (None,))[0]
                if _sc and lot.avg_cost > 0:
                    if _sc < lot.avg_cost:
                        lot.uw_streak += 1
                    else:
                        lot.uw_streak, lot.uw_trimmed = 0, False
            price = fill_price(code, marks.get(code))
'''),
    # 6. 长期水下减仓（出名单之后、其余退出之前）
    ('''            # 走势退出：**跟随均线**而非建仓日固定价。''',
     '''            if loss_age_days and lot.uw_streak >= loss_age_days and not lot.uw_trimmed:
                lot.uw_trimmed = True
                _keep_val = tranche_equity * loss_age_keep
                if lot.shares * sp > _keep_val + 1e-6:
                    _keep = int(_keep_val / sp / lot_size) * lot_size if lot_size else _keep_val / sp
                    _sell = lot.shares - _keep
                    _why = f"水下{loss_age_days}日·减至{loss_age_keep:.0%}"
                    if _keep <= 0 or _sell >= lot.shares * 0.999:
                        turnover += lot.shares * sp
                        close_lot(portfolio, code, day, sp, ledger=ledger, reason=_why + "·清仓")
                        sell_count += 1
                        stats["水下减仓·清仓"] += 1
                        continue
                    if _sell > 0:
                        log_partial_sell(ledger, day, code, _sell, sp, _why)
                        lot.shares -= _sell
                        portfolio.cash -= sell_dividend_tax(portfolio, lot, _sell, day)
                        portfolio.cash += _sell * sp - trade_fee(_sell * sp, day, "sell")
                        lot.proceeds += _sell * sp
                        lot.sells += 1
                        turnover += _sell * sp
                        sell_count += 1
                        stats["水下减仓·减仓"] += 1
                else:
                    stats["水下满期·已在上限内"] += 1
            # 走势退出：**跟随均线**而非建仓日固定价。'''),
    # 7. 水下满期期间加仓上限
    ('''                room = equity * position_cap - held_value
''',
     '''                room = equity * (min(position_cap, loss_age_keep)
                                 if (loss_age_days and code in portfolio.lots and portfolio.lots[code].uw_streak >= loss_age_days)
                                 else position_cap) - held_value
'''),
    # 8. 方案一的锚序列
    ('''def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
''',
     '''def _bt_anchor_series(codes: set[str], actions, lookback: int, column: str):
    """OI-247：逐票 (None, 窗口最低（末日口径）, 当日口径 → 末日口径仿射)；column = low／close。"""
    out = {}
    for code, series in _load_ohlcv_column(column, codes).items():
        days = sorted(series)
        if not days:
            continue
        scale, shift = exright_affine(days, actions.get(code, {}))
        q = [scale[i] * series[d] + shift[i] for i, d in enumerate(days)]
        swing, affine = {}, {}
        for i, d in enumerate(days):
            swing[d], affine[d] = min(q[max(0, i - lookback + 1): i + 1]), (scale[i], shift[i])
        out[code] = (None, swing, affine)
    return out


def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
'''),
    ('''    bt_lows = _bt_low_series_all(set(prices), actions) if args.bt_quiet else None
''',
     '''    bt_lows = _bt_low_series_all(set(prices), actions) if args.bt_quiet else None
    bt_anchor = (_bt_anchor_series(set(prices), actions, args.bt_stop_window, args.bt_stop_col)
                 if args.bt_quiet and (args.bt_stop_window != 20 or args.bt_stop_col != "low") else None)
'''),
    # 9. 命令行与传参
    ('''    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
''',
     '''    parser.add_argument("--bt-stop-window", type=int, default=20, help="研究开关（OI-247）：前低止损锚的窗口（缺省 20）")
    parser.add_argument("--bt-stop-col", choices=("low", "close"), default="low", help="研究开关（OI-247）：锚取全天最低或收盘最低")
    parser.add_argument("--bt-stop-release", action="store_true", help="研究开关（OI-247）：MA20 > MA60 后前低止损永久解除")
    parser.add_argument("--bt-no-anchor-nostop", action="store_true", help="研究开关（OI-247）：锚缺失的新建仓不设止损")
    parser.add_argument("--loss-age-days", type=int, default=0, help="研究开关（OI-247）：连续水下满 M 个信号日减仓（0 = 关）")
    parser.add_argument("--loss-age-keep", type=float, default=0.0, help="研究开关（OI-247）：减到信号日净资产的比例 X")
    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
'''),
    ('''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
''',
     '''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
                         bt_anchor=bt_anchor, bt_release=args.bt_stop_release, bt_no_anchor_nostop=args.bt_no_anchor_nostop,
                         loss_age_days=args.loss_age_days, loss_age_keep=args.loss_age_keep,
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

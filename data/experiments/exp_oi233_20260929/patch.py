"""OI-233 研究开关：在内存中给回测引擎打补丁，不改 `scripts/backtest_valuation_strategy.py`（影子组合按其指纹冻结）。

* `--zone-hold-pv H`（ZH）：持仓侧 `P/V` ≤ H 的日子不做价格止损（建仓锚／MA60 生效线照算，只是跌破不清仓）；
  `P/V` > H 或无估值时按现行止损。0 = 关。
* `--bt-quiet K`（BT，用户方案二）：未持仓候选的新建仓条件改为——信号日前 K 个交易日（含信号日）没有一天的
  最低价创 20 日新低，且信号日收盘 > MA5、> MA20；止损锚 = 信号日 20 日最低价（前复权比较，折回成交日口径），
  冻结不上移、除权同式折算，跌破即整仓清空。已持仓加仓与 `BASE` 相同。0 = 关。
* 用户方案一（不做价格止损）用现有 `--no-trend-stop`。

两个开关缺省关闭时，补丁后的引擎与原引擎逐位相同（`run.py` 用在册 `BASE` 锚点逐字段核对）。

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
    ('''        size_breaks: tuple[float, float] | None = None, size_e1: bool = False,
''',
     '''        size_breaks: tuple[float, float] | None = None, size_e1: bool = False,
        zone_hold_pv: float = 0.0, bt_quiet: int = 0, bt_lows: dict | None = None,
'''),
    # 2. 逐日循环外的判据
    ('''    def _e1_low(code: str, when: str) -> bool:
        return e1_table is not None and e1_low(e1_table, code, when, e1_min)
''',
     '''    def _e1_low(code: str, when: str) -> bool:
        return e1_table is not None and e1_low(e1_table, code, when, e1_min)

    def _bt_ok(code: str, when: str, close: float) -> bool:
        """OI-233 BT：近 bt_quiet 个交易日（含信号日）最低价未创 20 日新低，且信号日收盘 > MA5、> MA20。"""
        ma = mas.get(code, {}).get(when) or {}
        if 5 not in ma or 20 not in ma or not (close > ma[5] and close > ma[20]):
            return False
        rec = (bt_lows or {}).get(code)
        return bool(rec) and stabilized(rec[0], day_index[0].get(code, []), day_index[1].get(code, {}), when, quiet=bt_quiet)

    def _bt_anchor(code: str, when: str, fill_day: str) -> float | None:
        """OI-233 BT：信号日 20 日最低价（末日口径）折回成交日口径；成交日无行情时按信号日口径。"""
        rec = (bt_lows or {}).get(code)
        if not rec or when not in rec[1]:
            return None
        a, b = rec[2].get(fill_day) or rec[2][when]
        return (rec[1][when] - b) / a if a > 0 else None
'''),
    # 3. 止损标签
    ('''            stop_tag = f"建仓日MA{lot.entry_stop_ma}"
''',
     '''            stop_tag = f"建仓日MA{lot.entry_stop_ma}"
            if bt_quiet and not lot.entry_stop_ma and code not in left_topup:
                stop_tag = "建仓前低"                          # OI-233 BT
'''),
    # 4. ZH：持仓侧 P/V ≤ H 时跌破不清仓
    ('''            if pct_stop_when_rich and not is_rich(code, ratio):
''',
     '''            if zone_hold_pv and stop_trigger and ratio is not None and ratio <= zone_hold_pv:
                stats["止损·区内暂停（日）"] += 1                 # OI-233 ZH
                stop_trigger = ""
            if pct_stop_when_rich and not is_rich(code, ratio):
'''),
    # 5. BT：未持仓候选的新建仓条件
    ('''            def _trend_ok(r):
''',
     '''            def _trend_ok(r):
                if bt_quiet and r[0] not in portfolio.lots:      # OI-233 BT：新建仓改按前低企稳＋站上 MA5／MA20
                    return _bt_ok(r[0], buy_day, r[1])
'''),
    # 6. BT：建仓锚
    ('''                    left_topup.add(code)
                    stats["左侧半档·建仓"] += 1
''',
     '''                    left_topup.add(code)
                    stats["左侧半档·建仓"] += 1
                if bt_quiet:                                      # OI-233 BT：锚 = 信号日 20 日最低价（折到成交日口径）
                    _anchor = _bt_anchor(code, sig_day, day)
                    if _anchor:
                        lot.entry_stop, lot.entry_stop_ma = _anchor, 0
                        stats["前低建仓"] += 1
                    else:
                        stats["前低建仓·无锚沿用MA60"] += 1
'''),
    # 7. 命令行
    ('''    parser.add_argument("--size-e1", action="store_true", help="OI-224 SZ：E1 低于分界的股票不上调到 1.5 倍")
''',
     '''    parser.add_argument("--size-e1", action="store_true", help="OI-224 SZ：E1 低于分界的股票不上调到 1.5 倍")
    parser.add_argument("--zone-hold-pv", type=float, default=0.0, metavar="H",
                        help="研究开关（OI-233 ZH）：持仓侧 P/V ≤ H 时不做价格止损；0=关")
    parser.add_argument("--bt-quiet", type=int, default=0, metavar="K",
                        help="研究开关（OI-233 BT）：新建仓 = 近 K 日最低价未创 20 日新低且收盘 > MA5、> MA20，锚 = 信号日 20 日最低价；0=关")
'''),
    # 8. 逐票最低价序列（只在 BT 开时载入）
    ('''    if args.exright_stop == "frozen":
''',
     '''    bt_lows = _bt_low_series_all(set(prices), actions) if args.bt_quiet else None
    if args.exright_stop == "frozen":
'''),
    ('''def main() -> int:
''',
     '''def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
    """OI-233 BT：逐票 (当日最低价是否创 lookback 日新低, 窗口最低价（末日口径）, 当日口径 → 末日口径仿射 (A, B))。"""
    out = {}
    for code, series in _load_ohlcv_column("low", codes).items():
        days = sorted(series)
        if not days:
            continue
        scale, shift = exright_affine(days, actions.get(code, {}))
        q = [scale[i] * series[d] + shift[i] for i, d in enumerate(days)]
        flags, swing, affine = {}, {}, {}
        for i, d in enumerate(days):
            m = min(q[max(0, i - lookback + 1): i + 1])
            flags[d], swing[d], affine[d] = q[i] <= m + 1e-12, m, (scale[i], shift[i])
        out[code] = (flags, swing, affine)
    return out


def main() -> int:
'''),
    # 9. 传参
    ('''                         size_breaks=tuple(args.size_breaks) if args.size_breaks else None, size_e1=args.size_e1,
''',
     '''                         size_breaks=tuple(args.size_breaks) if args.size_breaks else None, size_e1=args.size_e1,
                         zone_hold_pv=args.zone_hold_pv, bt_quiet=args.bt_quiet, bt_lows=bt_lows,
'''),
]


def patched_source() -> str:
    text = SRC.read_text(encoding='utf-8')
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

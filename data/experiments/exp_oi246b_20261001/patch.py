"""OI-246 第二段研究开关：在内存中给原生回测引擎打补丁，不改 `scripts/backtest_valuation_strategy.py`。
开关缺省全关时与原生引擎逐位相同。

A2（谷底守卫深跌不买）：
* `--ta-drop D`：新建仓在信号日 250 日回报 < −D 且谷底守卫权重 v ≥ `--ta-vmin` 时挡下（不作建仓候选、不作换仓买入目标）。
* `--ta-vmin V`：v 门槛（缺省 0.5；取极小正数即 v > 0；取 −1 即不看 v）。
* `--ta-v-file`：`prep.py` 生成的逐票 v 分段。
* 250 日回报：信号日收盘对 250 个交易日前收盘，按正式公司行动折到信号日口径（同 OI-246 的 T4）；行情不足不判。

    from patch import load
    bt = load()          # 返回已打补丁的模块，并登记为 sys.modules['backtest_valuation_strategy']
    bt.TA_LOG            # 本次 run 挡下的（信号日, 代码）
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
        ta_drop: float | None = None, ta_vmin: float = 0.5, ta_v: dict | None = None, ta_ret: dict | None = None,
        ta_log: list | None = None,
'''),
    # 2. 新建仓走势判定之后挡下
    ('''            def _trend_ok(r):
                if bt_quiet and r[0] not in portfolio.lots:      # §9.3.1（v4.222，OI-233）：新建仓改按前低企稳＋站上 MA5／MA20
                    return _bt_ok(r[0], buy_day, r[1])
''',
     '''            def _ta_block(code, d):
                """OI-246 A2：谷底守卫权重达门槛且 250 日回报 < −D 的新建仓挡下。"""
                ret = (ta_ret or {}).get(code, {}).get(d)
                if ret is None or ret >= -ta_drop:
                    return False
                seq = (ta_v or {}).get(code)
                v = 0.0
                if seq:
                    j = bisect.bisect_right(seq[0], d) - 1
                    v = seq[1][j] if j >= 0 else 0.0
                return v >= ta_vmin

            def _trend_ok(r):
                if bt_quiet and r[0] not in portfolio.lots:      # §9.3.1（v4.222，OI-233）：新建仓改按前低企稳＋站上 MA5／MA20
                    _ok = _bt_ok(r[0], buy_day, r[1])
                    if _ok and ta_drop is not None and _ta_block(r[0], buy_day):
                        stats["A2·深跌挡下建仓"] += 1
                        if ta_log is not None:
                            ta_log.append((buy_day, r[0]))
                        return False
                    return _ok
'''),
    # 3. 250 日回报与 v 分段
    ('''def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
''',
     '''def _ta_ret_series(prices: dict, actions, lookback: int = 250) -> dict:
    """OI-246 A2：逐票 {日: 该日收盘对 lookback 个交易日前收盘的回报}，按正式公司行动折到当日口径。"""
    out = {}
    for code, series in prices.items():
        days = sorted(series)
        if len(days) <= lookback:
            continue
        scale, shift = exright_affine(days, actions.get(code, {}))
        q = [scale[i] * series[d] + shift[i] for i, d in enumerate(days)]
        rets = {}
        for i in range(lookback, len(days)):
            den = q[i - lookback] - shift[i]
            if den > 0:
                rets[days[i]] = (q[i] - shift[i]) / den - 1.0
        out[code] = rets
    return out


def _ta_v_load(path) -> dict:
    """OI-246 A2：`prep.py` 的 v 分段 → {代码: ([起始日], [v])}。"""
    out = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            days, vals = out.setdefault(row["security_code"], ([], []))
            days.append(row["from"])
            vals.append(float(row["v"]))
    return out


TA_LOG: list = []


def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
'''),
    ('''    bt_lows = _bt_low_series_all(set(prices), actions) if args.bt_quiet else None
''',
     '''    bt_lows = _bt_low_series_all(set(prices), actions) if args.bt_quiet else None
    ta_ret = _ta_ret_series(prices, actions) if args.ta_drop is not None else None
    ta_v = _ta_v_load(args.ta_v_file) if args.ta_drop is not None else None
'''),
    # 4. 命令行与传参
    ('''    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
''',
     '''    parser.add_argument("--ta-drop", type=float, default=None, help="研究开关（OI-246 A2）：250 日回报低于 −D 的谷底守卫新建仓挡下")
    parser.add_argument("--ta-vmin", type=float, default=0.5, help="研究开关（OI-246 A2）：谷底守卫权重门槛（−1 = 不看）")
    parser.add_argument("--ta-v-file", type=Path, default=None, help="研究开关（OI-246 A2）：prep.py 生成的 v 分段")
    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
'''),
    ('''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
''',
     '''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
                         ta_drop=args.ta_drop, ta_vmin=args.ta_vmin, ta_v=ta_v, ta_ret=ta_ret, ta_log=TA_LOG,
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

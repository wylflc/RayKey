"""OI-241 研究开关：在内存中给原生回测引擎（v4.222）打补丁，不改 `scripts/backtest_valuation_strategy.py`（影子组合按其指纹冻结）。
开关缺省全关时与原生引擎逐位相同（逐年 contrib 只记账，不进交易判据与 summary）。

* `--add-bt`（与 OI-235 A 同一规则）：已持仓加仓改按建仓条件（与 `--bt-quiet K` 同一判据：近 K 日最低价未创 20 日新低、
  收盘 > MA5 与 MA20），不再要求 MA20 > MA60；须与 `--bt-quiet` 同用。一档大小用现有 `--x`（买入）与 `--sell-x`（卖出）。
* 逐 (代码, 年) 累计 contrib（只记账，同 OI-238）。

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
     '''        bt_quiet: int = 0, bt_lows: dict | None = None, swap_ext: tuple | None = None, add_bt: bool = False,
'''),
    # 2. 已持仓加仓同建仓条件
    ('''                if bt_quiet and r[0] not in portfolio.lots:      # §9.3.1（v4.222，OI-233）：新建仓改按前低企稳＋站上 MA5／MA20
                    return _bt_ok(r[0], buy_day, r[1])
''',
     '''                if bt_quiet and r[0] not in portfolio.lots:      # §9.3.1（v4.222，OI-233）：新建仓改按前低企稳＋站上 MA5／MA20
                    return _bt_ok(r[0], buy_day, r[1])
                if add_bt and bt_quiet and r[0] in portfolio.lots and r[0] not in left_topup:
                    return _bt_ok(r[0], buy_day, r[1])           # OI-241（OI-235 A）：加仓同建仓条件，不要求 MA20 > MA60
'''),
    # 3. 逐 (代码, 年) contrib（只记账）
    ('''    contrib: dict[str, float] = collections.defaultdict(float)
''',
     '''    contrib: dict[str, float] = collections.defaultdict(float)
    contrib_year: dict = collections.defaultdict(float)   # OI-241：逐 (代码, 年) 累计
'''),
    ('''                contrib[code] += share
''',
     '''                contrib[code] += share
                contrib_year[(code, day[:4])] += share
'''),
    ('''"contrib": dict(contrib), "buys": buy_count,''',
     '''"contrib": dict(contrib), "contrib_year": {f"{c}|{y}": v for (c, y), v in contrib_year.items()}, "buys": buy_count,'''),
    # 4. 命令行与传参
    ('''    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
''',
     '''    parser.add_argument("--add-bt", action="store_true", help="研究开关（OI-241，OI-235 A）：已持仓加仓改按建仓条件（须与 --bt-quiet 同用）")
    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
'''),
    ('''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
''',
     '''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
                         add_bt=args.add_bt,
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

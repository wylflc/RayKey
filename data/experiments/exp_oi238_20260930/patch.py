"""OI-238 研究开关：在 OI-236 补丁（`../exp_oi236_20260929/patch.py`，其下依次是 OI-235、OI-233 补丁）之上再加内存补丁，
不改 `scripts/backtest_valuation_strategy.py`（影子组合按其指纹冻结）。开关缺省全关时与 OI-236 补丁引擎逐位相同
（逐年 contrib 只记账，不进交易判据与 summary）。

* `--nh-trim and|or|t|t1 [--nh-lookback N]`：让位减仓（盈利偏离让位源）加「未创新高」条件。「新高」= 当日最高价为含当日在内
  N 个交易日（缺省 20）最高价的最大值，按 §11.4 除权仿射折到同一口径（与 OI-233 前低同法）。信号日 = T，减仓日 = T+1
  （尾盘成交时当日最高价已知）。and：两日都未创新高才减；or：至少一日未创；t：只看信号日；t1：只看减仓日。
  被挡下的持仓不进让位源，当日若无其他让位源则不换仓。
* `--nh-gain`：涨幅 ≥ 110% 减持同样要求未创新高（与 `--nh-trim` 同一判据）。
* 逐 (代码, 年) 累计 contrib（只记账，同 OI-237 `detail.py`）。

    from patch import load
    bt = load()          # 返回已打补丁的模块，并登记为 sys.modules['backtest_valuation_strategy']
"""
import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('patch236', HERE.parent / 'exp_oi236_20260929' / 'patch.py')
patch236 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch236)
SRC = patch236.SRC

PATCHES = [
    # 1. run() 参数
    ('''        vd_drop: tuple | None = None, ext_trim: tuple | None = None,
''',
     '''        vd_drop: tuple | None = None, ext_trim: tuple | None = None,
        nh_mode: str | None = None, nh_highs: dict | None = None, nh_gain: bool = False,
'''),
    # 2. 状态
    ('''    vd_log: list = []               # OI-236 VD：(代码, 清仓日, 基准 V, 当时 V)
''',
     '''    vd_log: list = []               # OI-236 VD：(代码, 清仓日, 基准 V, 当时 V)
    nh_log: list = []               # OI-238：被「创新高」挡下的（类别, 代码, 减仓日）
    nh_seen: set = set()
'''),
    # 3. 判据
    ('''    def _bt_anchor(code: str, when: str, fill_day: str) -> float | None:
''',
     '''    def _nh_block(code: str, sig: str, exe: str) -> bool:
        """OI-238：信号日 sig／减仓日 exe 最高价是否创新高，按 nh_mode 决定是否挡下减仓。无行情的日子记未创新高。"""
        rec = (nh_highs or {}).get(code) or {}
        a, b = bool(rec.get(sig)), bool(rec.get(exe))
        return {"and": a or b, "or": a and b, "t": a, "t1": b}[nh_mode]

    def _bt_anchor(code: str, when: str, fill_day: str) -> float | None:
'''),
    # 4. 让位源：创新高则暂缓
    ('''                        ext_src.append((_cl / _mx[20], _cl / l.avg_cost, c))
''',
     '''                        if nh_mode and _nh_block(c, sig_day, day):   # OI-238：信号日／减仓日创新高则暂缓让位
                            if ("ext", c, day) not in nh_seen:
                                nh_seen.add(("ext", c, day))
                                nh_log.append(("ext", c, day))
                                stats["让位·创新高暂缓"] += 1
                            continue
                        ext_src.append((_cl / _mx[20], _cl / l.avg_cost, c))
'''),
    # 5. 涨幅减持：创新高则暂缓（--nh-gain）
    ('''                    gain_hit = ext_only = True
            if not value_rich and not gain_hit:
                continue
''',
     '''                    gain_hit = ext_only = True
            if nh_gain and nh_mode and gain_hit and not ext_only and not value_rich and _nh_block(code, sig_day, day):
                nh_log.append(("gain", code, day))                     # OI-238：涨幅减持同样暂缓
                stats["涨幅减持·创新高暂缓"] += 1
                gain_hit = False
            if not value_rich and not gain_hit:
                continue
'''),
    # 6. 逐 (代码, 年) contrib（只记账）
    ('''    contrib: dict[str, float] = collections.defaultdict(float)
''',
     '''    contrib: dict[str, float] = collections.defaultdict(float)
    contrib_year: dict = collections.defaultdict(float)   # OI-238：逐 (代码, 年) 累计
'''),
    ('''                contrib[code] += share
''',
     '''                contrib[code] += share
                contrib_year[(code, day[:4])] += share
'''),
    ('''"contrib": dict(contrib), "bb_log": bb_log,''',
     '''"contrib": dict(contrib), "contrib_year": {f"{c}|{y}": v for (c, y), v in contrib_year.items()}, "bb_log": bb_log,'''),
    # 7. 返回值
    ('''"vd_log": vd_log, "buys": buy_count,''',
     '''"vd_log": vd_log, "nh_log": nh_log, "buys": buy_count,'''),
    # 8. 逐票新高序列
    ('''    bt_lows = _bt_low_series_all(set(prices), actions) if args.bt_quiet else None
''',
     '''    bt_lows = _bt_low_series_all(set(prices), actions) if args.bt_quiet else None
    nh_highs = _nh_high_series_all(set(prices), actions, args.nh_lookback) if args.nh_trim else None
'''),
    ('''def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
''',
     '''def _nh_high_series_all(codes: set[str], actions, lookback: int = 20):
    """OI-238：逐票 {日: 当日最高价是否为含当日 lookback 日最高价的最大值}；价格按除权仿射折到末日口径（与 OI-233 前低同法）。"""
    out = {}
    for code, series in _load_ohlcv_column("high", codes).items():
        days = sorted(series)
        if not days:
            continue
        scale, shift = exright_affine(days, actions.get(code, {}))
        q = [scale[i] * series[d] + shift[i] for i, d in enumerate(days)]
        flags, window = {}, collections.deque()
        for i, d in enumerate(days):
            while window and window[0] <= i - lookback:
                window.popleft()
            while window and q[window[-1]] <= q[i] + 1e-12:
                window.pop()
            window.append(i)
            flags[d] = window[0] == i
        out[code] = flags
    return out


def _bt_low_series_all(codes: set[str], actions, lookback: int = 20):
'''),
    # 9. 命令行与传参
    ('''                        help="研究开关（OI-236 DEXT）：收盘 ≥ 均价×(1+G) 且 ≥ MA20×(1+D20) 即每日减一档，不等换仓触发")
''',
     '''                        help="研究开关（OI-236 DEXT）：收盘 ≥ 均价×(1+G) 且 ≥ MA20×(1+D20) 即每日减一档，不等换仓触发")
    parser.add_argument("--nh-trim", choices=("and", "or", "t", "t1"), default=None,
                        help="研究开关（OI-238）：让位减仓须信号日与减仓日最高价都未创新高（and）、至少一日未创（or）、只看信号日（t）或只看减仓日（t1）")
    parser.add_argument("--nh-lookback", type=int, default=20, help="研究开关（OI-238）：新高窗口（含当日）交易日数")
    parser.add_argument("--nh-gain", action="store_true", help="研究开关（OI-238）：涨幅减持同样要求未创新高")
'''),
    ('''                         ext_trim=tuple(args.ext_trim) if args.ext_trim else None,
''',
     '''                         ext_trim=tuple(args.ext_trim) if args.ext_trim else None,
                         nh_mode=args.nh_trim, nh_highs=nh_highs, nh_gain=args.nh_gain,
'''),
]


def patched_source() -> str:
    text = patch236.patched_source()
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

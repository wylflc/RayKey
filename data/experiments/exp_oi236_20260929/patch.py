"""OI-236 研究开关：在 OI-235 补丁（`../exp_oi235_20260929/patch.py`，其下是 OI-233 补丁）之上再加内存补丁，
不改 `scripts/backtest_valuation_strategy.py`（影子组合按其指纹冻结）。开关缺省全关时与 OI-235 补丁引擎逐位相同
（诊断计数只进 stats，不进交易判据与 summary）。

* `--vd-drop θ --vd-mode entry|peak`（VD）：持仓侧 V 较基准回落 ≥ θ 即整仓卖出；基准 = 建仓时持仓侧 V（entry）或
  持有期峰值（peak）。基准与再建仓阈值按 §11.4 同式除权折算；除权当日（信号日 V 仍是除权前口径）不判。
  清仓后该股持仓侧 V 回到「基准 ×(1−θ)」之上才可再建仓。现有 `--value-stop` 的峰值不随除权折算、起点取候选侧 V，不用。
* `--ext-trim G D20`（DEXT）：信号日收盘 ≥ 持仓均价 ×(1+G) 且 ≥ MA20 ×(1+D20) 即每日减一档（卖出一档），不等换仓触发，
  不过走势闸门；与涨幅减持同一路径，同日至多减一档。
* 诊断（常开，只记账）：换仓段之前记「资金不足一档」「合格集前列无未持仓候选」「持有持仓侧 P/V ≥ 1.30」的天数。
* 关闭换仓（SWOFF）不用补丁：`run.py` 从基准命令里去掉 `--swap`。

    from patch import load
    bt = load()          # 返回已打补丁的模块，并登记为 sys.modules['backtest_valuation_strategy']
"""
import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('patch235', HERE.parent / 'exp_oi235_20260929' / 'patch.py')
patch235 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch235)
SRC = patch235.SRC
RICH_DIAG = 1.30

PATCHES = [
    # 1. run() 参数
    ('''        add_bt: bool = False, swap_ext: tuple | None = None, swap_bb: tuple | None = None,
''',
     '''        add_bt: bool = False, swap_ext: tuple | None = None, swap_bb: tuple | None = None,
        vd_drop: tuple | None = None, ext_trim: tuple | None = None,
'''),
    # 2. 状态
    ('''    bb_log: list = []               # OI-235 B：让位减仓与买回流水
''',
     '''    bb_log: list = []               # OI-235 B：让位减仓与买回流水
    vd_block: dict = {}             # OI-236 VD：V 回落清仓后的再建仓阈值（持仓侧 V）
    vd_log: list = []               # OI-236 VD：(代码, 清仓日, 基准 V, 当时 V)
'''),
    # 3. 除权折算：V 基准与再建仓阈值
    ('''        if bb_pending:                                            # OI-235 B：待买回的价与股数按 §11.4 同式折算
''',
     '''        if vd_drop:                                               # OI-236 VD：V 基准与再建仓阈值按 §11.4 同式折算
            from corporate_actions import price_terms as _pt236
            for _c in set(portfolio.lots) | set(vd_block):
                _ev = actions.get(_c, {}).get(day)
                if not _ev:
                    continue
                _pc, _pr, _prr, _prp = _pt236(_ev)
                _adj = lambda x: max(0.0, (x + _prr * _prp - _pc) / (1.0 + _pr + _prr)) if x else x
                if _c in portfolio.lots:
                    _l = portfolio.lots[_c]
                    _l.vd_ref, _l.vd_peak = _adj(getattr(_l, 'vd_ref', 0.0)), _adj(getattr(_l, 'vd_peak', 0.0))
                if _c in vd_block:
                    vd_block[_c] = _adj(vd_block[_c])
        if bb_pending:                                            # OI-235 B：待买回的价与股数按 §11.4 同式折算
'''),
    # 4. VD：V 回到阈值之上才再建仓
    ('''                if bt_quiet and r[0] not in portfolio.lots:      # OI-233 BT：新建仓改按前低企稳＋站上 MA5／MA20
''',
     '''                if vd_block and r[0] not in portfolio.lots and r[0] in vd_block:   # OI-236 VD：V 回到阈值之上才再建仓
                    _v = (hold_today.get(r[0]) or (None, None, None))[1]
                    if not _v or _v <= vd_block[r[0]] or actions.get(r[0], {}).get(day):
                        return False
                    vd_block.pop(r[0])
                if bt_quiet and r[0] not in portfolio.lots:      # OI-233 BT：新建仓改按前低企稳＋站上 MA5／MA20
'''),
    # 5. VD：卖出段
    ('''            # 强势多头豁免减持：空间缩小不卖，等趋势自己走坏或财报更新带改变格局。
''',
     '''            if vd_drop and not actions.get(code, {}).get(day):   # OI-236 VD：持仓侧 V 较基准回落 ≥ θ 即清仓（除权当日不判）
                _v = (hold_today.get(code) or (None, None, None))[1]
                if _v and _v > 0:
                    if not getattr(lot, 'vd_ref', 0.0):
                        lot.vd_ref = lot.vd_peak = _v
                    lot.vd_peak = max(getattr(lot, 'vd_peak', 0.0), _v)
                    _ref = lot.vd_peak if vd_drop[1] == 'peak' else lot.vd_ref
                    if _v <= _ref * (1.0 - vd_drop[0]):
                        vd_block[code] = _ref * (1.0 - vd_drop[0])
                        vd_log.append((code, day, _ref, _v))
                        stats["V回落·清仓"] += 1
                        turnover += lot.shares * sp
                        close_lot(portfolio, code, day, sp, ledger=ledger, reason=f"V回落≥{vd_drop[0]:.0%}清仓")
                        sell_count += 1
                        continue
            # 强势多头豁免减持：空间缩小不卖，等趋势自己走坏或财报更新带改变格局。
'''),
    # 6. VD：新建仓记基准
    ('''                portfolio.lots[code] = lot
''',
     '''                portfolio.lots[code] = lot
                if vd_drop:                                               # OI-236 VD：建仓时的持仓侧 V 作回落基准
                    _v0 = (hold_today.get(code) or (None, None, None))[1]
                    lot.vd_ref = lot.vd_peak = _v0 if _v0 and _v0 > 0 else 0.0
'''),
    # 7. DEXT：盈利＋偏离即减一档
    ('''            if not value_rich and not gain_hit:
                continue
''',
     '''            ext_only = False
            if ext_trim and not gain_hit and not value_rich and lot.avg_cost > 0:   # OI-236 DEXT：不等换仓触发
                _cl = today.get(code, (None,))[0]
                _mx = mas.get(code, {}).get(sig_day, {})
                if _cl and _mx.get(20) and _cl >= lot.avg_cost * (1.0 + ext_trim[0]) and _cl >= _mx[20] * (1.0 + ext_trim[1]):
                    gain_hit = ext_only = True
            if not value_rich and not gain_hit:
                continue
'''),
    ('''            sell_tag = rich_tag if value_rich else (f"阶梯≥{ladder_rung:.0%}" if gain_ladder else f"涨幅≥{gain_sell:.0%}")
''',
     '''            sell_tag = rich_tag if value_rich else ("盈利偏离" if ext_only else (f"阶梯≥{ladder_rung:.0%}" if gain_ladder else f"涨幅≥{gain_sell:.0%}"))
'''),
    # 8. 诊断（只记账）
    ('''        if swap and eligible:
            for code, close, value, ratio in (eligible[:max_positions] if swap_mode == "legacy" else []):
''',
     '''        _rich236 = [c for c in portfolio.lots
                    if (hold_today.get(c) or (None, None, None))[2] is not None and hold_today[c][2] >= ''' + f'{RICH_DIAG}' + ''']
        if _rich236:
            stats["诊断·持有高估日"] += 1
        if funds_available() < (lump_sum or budget):                  # OI-236 诊断：只记账，不进判据
            stats["诊断·资金不足日"] += 1
            _nonheld236 = any(r[0] not in portfolio.lots for r in eligible[:max_positions])
            if not _nonheld236:
                stats["诊断·资金不足且无未持仓候选"] += 1
            if _rich236:
                stats["诊断·资金不足且持有高估"] += 1
                if not _nonheld236:
                    stats["诊断·持有高估且无触发者"] += 1
        if swap and eligible:
            for code, close, value, ratio in (eligible[:max_positions] if swap_mode == "legacy" else []):
'''),
    # 9. 返回值
    ('''"contrib": dict(contrib), "bb_log": bb_log, "buys": buy_count,''',
     '''"contrib": dict(contrib), "bb_log": bb_log, "vd_log": vd_log, "buys": buy_count,'''),
    # 10. 命令行与传参
    ('''    parser.add_argument("--value-sell-full", action="store_true", help="研究开关（OI-235 C）：--sell-line 触发即整仓卖出")
''',
     '''    parser.add_argument("--value-sell-full", action="store_true", help="研究开关（OI-235 C）：--sell-line 触发即整仓卖出")
    parser.add_argument("--vd-drop", type=float, default=0.0, metavar="θ",
                        help="研究开关（OI-236 VD）：持仓侧 V 较基准回落 ≥ θ 即清仓，V 回到阈值之上才再建仓；0=关")
    parser.add_argument("--vd-mode", choices=("entry", "peak"), default="entry",
                        help="研究开关（OI-236 VD）：基准 = 建仓时持仓侧 V（entry）或持有期峰值（peak）")
    parser.add_argument("--ext-trim", type=float, nargs=2, default=None, metavar=("G", "D20"),
                        help="研究开关（OI-236 DEXT）：收盘 ≥ 均价×(1+G) 且 ≥ MA20×(1+D20) 即每日减一档，不等换仓触发")
'''),
    ('''                         value_sell_ungated=args.value_sell_ungated, value_sell_full=args.value_sell_full,
''',
     '''                         value_sell_ungated=args.value_sell_ungated, value_sell_full=args.value_sell_full,
                         vd_drop=(args.vd_drop, args.vd_mode) if args.vd_drop else None,
                         ext_trim=tuple(args.ext_trim) if args.ext_trim else None,
'''),
]


def patched_source() -> str:
    text = patch235.patched_source()
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

"""OI-224 第二批研究开关补丁（回测引擎）：`--left-stop X`／`--left-e1`（LS）、`--deep-stop-pv D`／`--deep-stop-e1`（DPt）、
`--size-breaks LO HI`／`--size-e1`（SZ）。缺省全关，关时逐位不变。

    python3 patch_engine.py <目标 .py>
"""
import sys
from pathlib import Path

PATCHES = [
    # 1. run() 参数
    ('''        reentry_e1: bool = False, swap_protect_e1: bool = False,
''',
     '''        reentry_e1: bool = False, swap_protect_e1: bool = False,
        left_stop: float = 0.0, left_e1: bool = False, deep_stop_pv: float = 0.0, deep_stop_e1: bool = False,
        size_breaks: tuple[float, float] | None = None, size_e1: bool = False,
'''),
    # 2. 逐日循环外的状态与一档系数
    ('''    def _e1_low(code: str, when: str) -> bool:
        return e1_table is not None and e1_low(e1_table, code, when, e1_min)
''',
     '''    def _e1_low(code: str, when: str) -> bool:
        return e1_table is not None and e1_low(e1_table, code, when, e1_min)

    left_used: set[str] = set()                  # OI-224 LS：本次在区内已左侧建过半档的代码（出区即清）
    left_topup: set[str] = set()                 # OI-224 LS：左侧半档待补足的持仓
    left_today: set[str] = set()                 # OI-224 LS：当日左侧半档候选（未持仓、在区内、走势未满足、近 5 日未创 20 日新低）

    def _size_k(code: str, ratio: float, when: str) -> float:
        """OI-224 SZ：一档系数——P/V ≤ LO 为 1.5、LO～HI 为 1.0、HI 以上为 0.5；E1 变体对 E1 最差一档不上调。"""
        if not size_breaks:
            return 1.0
        k = 1.5 if ratio <= size_breaks[0] else 1.0 if ratio <= size_breaks[1] else 0.5
        return 1.0 if k > 1.0 and size_e1 and _e1_low(code, when) else k
'''),
    # 3. 止损线：左侧半档标签与深度低估放宽（DPt）
    ('''            stop_tag = f"建仓日MA{lot.entry_stop_ma}"
''',
     '''            stop_tag = f"建仓日MA{lot.entry_stop_ma}"
            if code in left_topup:
                stop_tag = f"左侧半档·成交价×{1.0 - left_stop:g}"
            if deep_stop_pv and stop_level and ratio is not None and ratio < deep_stop_pv \\
                    and not (deep_stop_e1 and _e1_low(code, judge_day)):
                ma120 = mas.get(code, {}).get(judge_day, {}).get(120)
                if ma120 and ma120 < stop_level:                 # OI-224 DPt：深度低估持仓的生效线放宽到 MA120
                    stop_level, stop_tag = ma120, "深度低估·MA120"
'''),
    # 4. 走势闸门前留出区内候选；左侧半档待补足的持仓按新建仓判走势
    ('''            relaxed_entry.clear()
''',
     '''            relaxed_entry.clear()
            left_today.clear()
            pre_trend = eligible
'''),
    ('''                if addon_trend == "ma-only" and r[0] in portfolio.lots:
                    return True                      # 已持仓：只看均线排列，不看价格位置''',
     '''                if addon_trend == "ma-only" and r[0] in portfolio.lots and r[0] not in left_topup:
                    return True                      # 已持仓：只看均线排列，不看价格位置'''),
    ('''            eligible = [r for r in eligible if _trend_ok(r)]
''',
     '''            eligible = [r for r in eligible if _trend_ok(r)]
            if left_stop:
                left_topup.intersection_update(portfolio.lots)
                for r in pool:
                    if r[0] in left_used and r[3] > buy_line(r[0]):
                        left_used.discard(r[0])      # 出区：下次进区可再左侧建仓
                _passed = {r[0] for r in eligible}
                for r in pre_trend:
                    _lc = r[0]
                    if (_lc not in _passed and _lc not in portfolio.lots and _lc not in left_used
                            and not (left_e1 and _e1_low(_lc, buy_day))
                            and stabilized(lows.get(_lc, {}), day_index[0].get(_lc, []), day_index[1].get(_lc, {}), buy_day)):
                        left_today.add(_lc)
                left_rows = [r for r in pre_trend if r[0] in left_today]
'''),
    ('''        if strategy == "trend" and entry_mode in ("trend", "both"):
            # `trend_tol`''',
     '''        left_rows: list = []                         # OI-224 LS：当日左侧半档候选行（换仓之后并入买入顺序）
        if strategy == "trend" and entry_mode in ("trend", "both"):
            # `trend_tol`'''),
    # 5. T+1 确认：左侧半档不判均线、改判仍未创新低；待补足者按新建仓判收盘站上均线
    ('''            if strategy == "trend" and entry_mode in ("trend", "both"):
                ma_exec = mas.get(code, {}).get(day) or {}''',
     '''            if code in left_today:
                if not stabilized(lows.get(code, {}), day_index[0].get(code, []), day_index[1].get(code, {}), day):
                    stats["T+1确认·左侧半档取消·创新低"] += 1
                    buy_confirmation_cache[code] = False
                    return False
                buy_confirmation_cache[code] = True
                return True
            if strategy == "trend" and entry_mode in ("trend", "both"):
                ma_exec = mas.get(code, {}).get(day) or {}'''),
    ('''                if not (addon_trend == "ma-only" and code in held_for_confirmation) \\
                        and not exec_close > ma_exec[trend_ma[0]] * k:''',
     '''                if not (addon_trend == "ma-only" and code in held_for_confirmation and code not in left_topup) \\
                        and not exec_close > ma_exec[trend_ma[0]] * k:'''),
    # 6. 左侧半档候选按 P/V 并入买入顺序（不作换仓目标）
    ('''        buy_plan = ([(r, pair_alloc[r[0]]) for r in eligible[:max_positions] if pair_alloc.get(r[0], 0.0) > 0]''',
     '''        if left_rows:
            _have = {_row[0] for _row in eligible}
            _extra = sorted((r for r in left_rows if r[0] not in _have), key=_key)
            _merged, _i = [], 0
            for _row in eligible:                # 不得用 x：x 是一档比例参数
                while _i < len(_extra) and _key(_extra[_i]) < _key(_row):
                    _merged.append(_extra[_i]); _i += 1
                _merged.append(_row)
            eligible = _merged + _extra[_i:]
        buy_plan = ([(r, pair_alloc[r[0]]) for r in eligible[:max_positions] if pair_alloc.get(r[0], 0.0) > 0]'''),
    # 7. 一档金额：SZ 系数、左侧半档与补足各半档
    ('''            if pair_amount is not None:
                amount = min(pair_amount, avail)      # 配对换仓定向额度：不按一档，按收到多少买多少
            elif lump_sum:
                amount = min(equity * lump_sum, avail)
            else:
                amount = min(budget if (strategy == "valuation" or tranche)
                             else equity / max_positions, avail)''',
     '''            tier_amt = budget
            if pair_amount is not None:
                amount = min(pair_amount, avail)      # 配对换仓定向额度：不按一档，按收到多少买多少
            elif lump_sum:
                amount = min(equity * lump_sum, avail)
            else:
                if size_breaks or left_stop:          # OI-224 SZ／LS：一档乘估值深度系数；左侧半档与补足各半档
                    tier_amt = budget * _size_k(code, ratio, buy_day) * (
                        0.5 if (code in left_today and code not in portfolio.lots) or code in left_topup else 1.0)
                amount = min(tier_amt if (strategy == "valuation" or tranche)
                             else equity / max_positions, avail)'''),
    ('''            if min_buy_frac and amount < budget * min_buy_frac:''',
     '''            if min_buy_frac and amount < tier_amt * min_buy_frac:'''),
    ('''                        ready = cooldown_ready(lot_counters_buy, code, bp * lot_size, budget)''',
     '''                        ready = cooldown_ready(lot_counters_buy, code, bp * lot_size, tier_amt)'''),
    # 8. 建仓：左侧半档止损为成交价 ×(1−X)；补足时改用常规锚
    ('''                if code in relaxed_entry and ma.get(20):          # OI-224 RE：重入仓的止损锚取成交日 MA20
                    lot.entry_stop, lot.entry_stop_ma = ma[20], 20
                    stats["止损后重入·建仓"] += 1
                portfolio.lots[code] = lot
''',
     '''                if code in relaxed_entry and ma.get(20):          # OI-224 RE：重入仓的止损锚取成交日 MA20
                    lot.entry_stop, lot.entry_stop_ma = ma[20], 20
                    stats["止损后重入·建仓"] += 1
                if code in left_today:                            # OI-224 LS：左侧半档，止损为成交价 ×(1−X)
                    lot.entry_stop, lot.entry_stop_ma = fill * (1.0 - left_stop), 0
                    left_used.add(code)
                    left_topup.add(code)
                    stats["左侧半档·建仓"] += 1
                portfolio.lots[code] = lot
            elif code in left_topup:                              # OI-224 LS：走势满足后补足半档，改用常规锚
                ma = mas.get(code, {}).get(day) or mas.get(code, {}).get(sig_day, {})
                lot.entry_stop, lot.entry_stop_ma = entry_stop_price(
                    ma, fill if entry_below_ma60 == "skip_fill" else close, stop_ma,
                    force_ma60=(entry_below_ma60 == "ma60_stop"))
                left_topup.discard(code)
                stats["左侧半档·补足"] += 1
'''),
    # 9. 调用
    ('''                         reentry_e1=args.reentry_e1, swap_protect_e1=args.swap_protect_e1,
''',
     '''                         reentry_e1=args.reentry_e1, swap_protect_e1=args.swap_protect_e1,
                         left_stop=args.left_stop, left_e1=args.left_e1,
                         deep_stop_pv=args.deep_stop_pv, deep_stop_e1=args.deep_stop_e1,
                         size_breaks=tuple(args.size_breaks) if args.size_breaks else None, size_e1=args.size_e1,
'''),
    # 10. 命令行
    ('''    parser.add_argument("--swap-protect-e1", action="store_true",
                        help="OI-224：--swap-out-min-pv 的保护对 E1 低于分界的持仓不生效")
''',
     '''    parser.add_argument("--swap-protect-e1", action="store_true",
                        help="OI-224：--swap-out-min-pv 的保护对 E1 低于分界的持仓不生效")
    parser.add_argument("--left-stop", type=float, default=0.0, metavar="X",
                        help="研究开关（OI-224 LS）：未持仓候选在买入区而走势未满足、近 5 日未创 20 日新低时先建半档（本次在区内限一次，"
                             "出区重置），止损为成交价 ×(1−X)；收盘 > MA20 > MA60 后补足半档并改用常规锚。0=关（缺省）")
    parser.add_argument("--left-e1", action="store_true", help="OI-224 LS：E1 低于分界的股票不做左侧半档")
    parser.add_argument("--deep-stop-pv", type=float, default=0.0, metavar="D",
                        help="研究开关（OI-224 DPt）：持仓侧 P/V < D 时生效止损线取 min(现行线, 当日 MA120)。0=关（缺省）")
    parser.add_argument("--deep-stop-e1", action="store_true", help="OI-224 DPt：E1 低于分界的持仓不放宽")
    parser.add_argument("--size-breaks", type=float, nargs=2, default=None, metavar=("LO", "HI"),
                        help="研究开关（OI-224 SZ）：一档乘系数——候选侧 P/V ≤ LO 为 1.5 倍、LO～HI 为 1.0 倍、HI 以上为 0.5 倍"
                             "（配对换仓定向额度不变）。缺省关")
    parser.add_argument("--size-e1", action="store_true", help="OI-224 SZ：E1 低于分界的股票不上调到 1.5 倍")
'''),
]


def main():
    path = Path(sys.argv[1])
    text = path.read_text(encoding='utf-8')
    for old, new in PATCHES:
        n = text.count(old)
        assert n == 1, (n, old[:80])
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')
    print('patched', path, len(PATCHES))


if __name__ == '__main__':
    main()

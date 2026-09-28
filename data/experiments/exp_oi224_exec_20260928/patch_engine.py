"""OI-224 研究开关补丁（回测引擎）：`--reentry-days N`、`--e1-table`、`--e1-min`、`--reentry-e1`、`--swap-protect-e1`。

    python3 patch_engine.py <目标 .py>
"""
import sys
from pathlib import Path

PATCHES = [
    # 1. 模块级：E1 时点表
    ('''def entry_stop_price(ma: dict[int, float], close: float, stop_ma: int,''',
     '''def load_e1_table(path: Path) -> dict[str, tuple[list[str], list[float | None]]]:
    """OI-224：E1（近三个财年经营现金流 ÷ 归母净利）时点表 → {代码: ([可得日], [E1])}，按可得日升序。"""
    out: dict[str, tuple[list[str], list[float | None]]] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = sorted(csv.DictReader(handle), key=lambda r: (r["security_code"], r["available_at"]))
    for r in rows:
        dates, values = out.setdefault(r["security_code"].zfill(6), ([], []))
        dates.append(r["available_at"])
        values.append(float(r["e1"]) if r.get("e1") else None)
    return out


def e1_low(table: dict, code: str, day: str, threshold: float) -> bool:
    """`day` 当日可得的最近一行 E1 低于阈值；缺失视为不低（不改变规则）。"""
    entry = table.get(code)
    if not entry:
        return False
    i = bisect.bisect_right(entry[0], day) - 1
    return i >= 0 and entry[1][i] is not None and entry[1][i] < threshold


''', 'before'),
    # 2. simulate 参数
    ('''        swap_out_min_pv: float = 0.0,
        mkt: dict[str, float] | None = None, mkt_crash_days: int = 0,''',
     '''        swap_out_min_pv: float = 0.0,
        reentry_days: int = 0, e1_table: dict | None = None, e1_min: float = 0.84,
        reentry_e1: bool = False, swap_protect_e1: bool = False,
        mkt: dict[str, float] | None = None, mkt_crash_days: int = 0,''', 'replace'),
    # 3. 主循环前的状态
    ('''    for day_no, day in enumerate(days):''',
     '''    last_stop_day: dict[str, int] = {}           # OI-224 RE：代码 → 最近一次建仓止损清仓的交易日序号
    relaxed_entry: set[str] = set()              # OI-224 RE：当日只因重入放宽而过走势条件的代码

    def _e1_low(code: str, when: str) -> bool:
        return e1_table is not None and e1_low(e1_table, code, when, e1_min)

''', 'before'),
    # 4. 止损清仓记日
    ('''                close_lot(portfolio, code, day, sp, ledger=ledger,
                          reason=f"{trigger_reason}{stop_tag}止损", net_reg=net_reg)
                sell_count += 1
                continue''',
     '''                close_lot(portfolio, code, day, sp, ledger=ledger,
                          reason=f"{trigger_reason}{stop_tag}止损", net_reg=net_reg)
                last_stop_day[code] = day_no
                sell_count += 1
                continue''', 'replace'),
    # 5. 信号日走势条件：重入放宽
    ('''            def _trend_ok(r):
                ma = mas.get(r[0], {}).get(buy_day)
                if not ma or not all(w in ma for w in trend_ma):
                    return False
                if len(trend_ma) >= 2 and not ma[trend_ma[0]] > ma[trend_ma[1]] * k:
                    return False''',
     '''            relaxed_entry.clear()

            def _reentry_ok(code):
                """OI-224 RE：建仓止损清仓后 N 个交易日内的未持仓代码，新建仓免 MA20 > MA60（E1 变体对 E1 最差一档不放宽）。"""
                return (reentry_days > 0 and code not in portfolio.lots and code in last_stop_day
                        and day_no - last_stop_day[code] <= reentry_days
                        and not (reentry_e1 and _e1_low(code, buy_day)))

            def _trend_ok(r):
                ma = mas.get(r[0], {}).get(buy_day)
                if not ma or not all(w in ma for w in trend_ma):
                    return False
                if len(trend_ma) >= 2 and not ma[trend_ma[0]] > ma[trend_ma[1]] * k:
                    if _reentry_ok(r[0]) and r[1] > ma[trend_ma[0]] * k:
                        relaxed_entry.add(r[0])
                        return True
                    return False''', 'replace'),
    # 6. T+1 确认同改
    ('''                if (len(trend_ma) >= 2
                        and not ma_exec[trend_ma[0]] > ma_exec[trend_ma[1]] * k):''',
     '''                if (len(trend_ma) >= 2 and code not in relaxed_entry
                        and not ma_exec[trend_ma[0]] > ma_exec[trend_ma[1]] * k):''', 'replace'),
    # 7. 重入仓止损锚取成交日 MA20
    ('''                lot.entry_stop, lot.entry_stop_ma = entry_stop_price(
                    ma, fill if entry_below_ma60 == "skip_fill" else close, stop_ma,
                    force_ma60=(entry_below_ma60 == "ma60_stop"))''',
     '''                lot.entry_stop, lot.entry_stop_ma = entry_stop_price(
                    ma, fill if entry_below_ma60 == "skip_fill" else close, stop_ma,
                    force_ma60=(entry_below_ma60 == "ma60_stop"))
                if code in relaxed_entry and ma.get(20):          # OI-224 RE：重入仓的止损锚取成交日 MA20
                    lot.entry_stop, lot.entry_stop_ma = ma[20], 20
                    stats["止损后重入·建仓"] += 1''', 'replace'),
    # 8. 换出源保护的 E1 变体
    ('''                        and (not swap_out_min_pv or src_pv(c) >= swap_out_min_pv)''',
     '''                        and (not swap_out_min_pv or src_pv(c) >= swap_out_min_pv
                             or (swap_protect_e1 and _e1_low(c, sig_day)))''', 'replace'),
    # 9. 调用
    ('''                         swap_out_min_pv=args.swap_out_min_pv,''',
     '''                         swap_out_min_pv=args.swap_out_min_pv,
                         reentry_days=args.reentry_days, e1_min=args.e1_min,
                         e1_table=load_e1_table(args.e1_table) if args.e1_table else None,
                         reentry_e1=args.reentry_e1, swap_protect_e1=args.swap_protect_e1,''', 'replace'),
    # 10. 命令行
    ('''    parser.add_argument("--swap-out-min-pv", type=float, default=0.0, metavar="X",''',
     '''    parser.add_argument("--reentry-days", type=int, default=0, metavar="N",
                        help="研究开关（OI-224 RE）：建仓止损清仓后 N 个交易日内、P/V 仍在买入区的再建仓只要求收盘 > MA20，"
                             "止损锚取成交日 MA20；0=关（缺省）")
    parser.add_argument("--e1-table", type=Path, default=None, metavar="CSV",
                        help="研究开关（OI-224）：E1 时点表（security_code,report_date,available_at,e1）")
    parser.add_argument("--e1-min", type=float, default=0.84, help="OI-224 E1 变体的最差一档分界（缺省 0.84）")
    parser.add_argument("--reentry-e1", action="store_true", help="OI-224：E1 低于分界的股票不做重入放宽")
    parser.add_argument("--swap-protect-e1", action="store_true",
                        help="OI-224：--swap-out-min-pv 的保护对 E1 低于分界的持仓不生效")
''', 'before'),
]


def main():
    path = Path(sys.argv[1])
    text = path.read_text(encoding='utf-8')
    for old, new, mode in PATCHES:
        assert text.count(old) == 1, (old[:70], text.count(old))
        text = text.replace(old, new) if mode == 'replace' else text.replace(old, new + old)
    for mod in ('import bisect', 'import csv'):
        assert mod in text, mod
    path.write_text(text, encoding='utf-8')
    print('patched', path)


if __name__ == '__main__':
    main()

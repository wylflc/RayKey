"""OI-227 研究开关补丁（回测引擎）：`--bank-buy-line L`——银行（divspread 判定的银行保险减去保险）的买入线改为 L，
非金融与保险不变；缺省 0＝关，关时逐位不变。

    python3 patch_engine.py <目标 .py>
"""
import sys
from pathlib import Path

PATCHES = [
    ('''def entry_stop_price(ma: dict[int, float], close: float, stop_ma: int,''',
     '''def load_bank_codes() -> frozenset:
    """OI-227：银行代码（divspread 判定的银行保险减去保险，与 `bank_valuation.bank_codes` 同源）。"""
    import bank_valuation
    return frozenset(bank_valuation.bank_codes(ROOT / "data/raw/a_share_securities.csv"))


def entry_stop_price(ma: dict[int, float], close: float, stop_ma: int,'''),
    ('''        size_breaks: tuple[float, float] | None = None, size_e1: bool = False,
''',
     '''        size_breaks: tuple[float, float] | None = None, size_e1: bool = False,
        bank_buy_line: float = 0.0, bank_codes: frozenset = frozenset(),
'''),
    ('''    def buy_line(code: str) -> float:
        if use_mos:''',
     '''    def buy_line(code: str) -> float:
        if bank_buy_line and code in bank_codes:    # OI-227：银行单独买入线
            return bank_buy_line
        if use_mos:'''),
    ('''                         size_breaks=tuple(args.size_breaks) if args.size_breaks else None, size_e1=args.size_e1,
''',
     '''                         size_breaks=tuple(args.size_breaks) if args.size_breaks else None, size_e1=args.size_e1,
                         bank_buy_line=args.bank_buy_line,
                         bank_codes=load_bank_codes() if args.bank_buy_line else frozenset(),
'''),
    ('''    parser.add_argument("--size-e1", action="store_true", help="OI-224 SZ：E1 低于分界的股票不上调到 1.5 倍")
''',
     '''    parser.add_argument("--size-e1", action="store_true", help="OI-224 SZ：E1 低于分界的股票不上调到 1.5 倍")
    parser.add_argument("--bank-buy-line", type=float, default=0.0, metavar="L",
                        help="研究开关（OI-227）：银行（不含保险）的买入线改为 L，非金融与保险不变。0=关（缺省）")
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

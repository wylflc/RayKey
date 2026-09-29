"""v4.222 落地：把 OI-233 BT（前低企稳建仓）与 OI-235 B（盈利偏离让位换仓源）两个研究开关从内存补丁移入
`scripts/backtest_valuation_strategy.py`，成为引擎原生开关 `--bt-quiet K` 与 `--swap-ext G D20 D5`。

代码逐字取自 `exp_oi233_20260929/patch.py` 与 `exp_oi235_20260929/patch.py`（判据与顺序不变），只去掉未采纳的部分：
ZH（区内不止损）、A（加仓同建仓条件）、做 T 买回、估值减持不过闸门／整仓。开关缺省关闭时引擎逐位不变。
移入后须用 `reproduce.py` 证明：原生引擎在在册 `BASE` 上逐字段复现 OI-237 的 BASE 行，加三个开关后复现 OI-237 的 S15 行。

    python3 port_engine.py          # 就地改写引擎（已移入则报错退出）
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / 'scripts' / 'backtest_valuation_strategy.py'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


p233 = _load('p233', ROOT / 'data/experiments/exp_oi233_20260929/patch.py').PATCHES
p235 = _load('p235', ROOT / 'data/experiments/exp_oi235_20260929/patch.py').PATCHES
EXT_TAG = '·盈利偏离让位'


def _ext(new: str) -> str:
    return new.replace("''' + EXT_TAG + '''", EXT_TAG).replace('"""+EXT_TAG+"""', EXT_TAG)


EDITS = [
    # run() 参数
    (p233[0][0], p233[0][0] + '''        bt_quiet: int = 0, bt_lows: dict | None = None, swap_ext: tuple | None = None,
'''),
    # BT 判据与建仓锚（逐字取自 OI-233）
    p233[1],
    # 止损标签
    p233[2],
    # 新建仓条件
    p233[4],
    # 建仓锚
    p233[5],
    # 盈利偏离让位源（逐字取自 OI-235 B）
    p235[4],
    (p235[5][0], _ext(p235[5][1])),
    # 命令行
    (p233[6][0], p233[6][0] + '''    parser.add_argument("--bt-quiet", type=int, default=0, metavar="K",
                        help="§9.3.1 新建仓走势（v4.222，OI-233）：近 K 个交易日（含信号日）最低价未创 20 日新低，且信号日收盘 > MA5、> MA20；"
                             "锚 = 信号日 20 日最低价（只在价格止损开着时用）；0=关（旧口径：收盘 > MA20 > MA60）")
    parser.add_argument("--swap-ext", type=float, nargs=3, default=None, metavar=("G", "D20", "D5"),
                        help="§9.3.1 换仓卖出源（v4.222，OI-235／OI-236）：信号日收盘 ≥ 持仓均价×(1+G) 且 ≥ MA20×(1+D20)、≥ MA5×(1+D5)"
                             "（0=不要求）的持仓中取收盘÷MA20 最大者，不比 P/V 边际、不要求弱势；取代弱势＋边际源")
'''),
    # 逐票最低价序列
    p233[7],
    p233[8],
    # 传参
    (p233[9][0], p233[9][0] + '''                         bt_quiet=args.bt_quiet, bt_lows=bt_lows, swap_ext=tuple(args.swap_ext) if args.swap_ext else None,
'''),
]


def main():
    text = ENGINE.read_text(encoding='utf-8')
    assert 'bt_quiet' not in text and 'swap_ext' not in text, '引擎已含 bt_quiet／swap_ext，不重复移入'
    for old, new in EDITS:
        assert text.count(old) == 1, ('anchor not unique', old[:90])
        text = text.replace(old, new)
    for tag in ('OI-235 B', 'OI-233 BT'):                 # 注释改写为现行出处
        text = text.replace(f'# {tag}：', f'# §9.3.1（v4.222，{tag.split()[0]}）：')
    ENGINE.write_text(text, encoding='utf-8')
    print('ported:', len(EDITS), 'edits')


if __name__ == '__main__':
    main()

"""线对齐（§12.30 / OI-045）：换宇宙或换估值口径后，重解回测对照臂的三条线。

`P/V` 的分布整体平移之后，同一条名义线放行的合格面完全不同，
比出来的是「两条不同宽度的闸门」而不是「两套设定」。
故对每条臂重解一条线，使**面板在册观测中落在线同侧的比例与基准相同**。

**三条线都要对齐，只对齐买入线会得到污染的比较**（§12.45 踩过一次）：
只对齐买入线时 `P/V` 中位降到 0.89 而减持线仍是基准值，卖出机构整个休眠
（换手 6.81 → 2.10），方向没错但幅度差了 4pp。
- **买入线**按「`P/V ≤ 线` 的比例」对齐（下侧分位）；
- **减持线**按「`P/V ≥ 线` 的比例」对齐（上侧分位）；
- **换仓最小改善**按买入线的缩放比例同倍缩放（它是 `P/V` 的差，不是分位）。

**基准侧与待对齐侧可以是不同的面板**——V3 → V4 那次正是宇宙变了而估值文件没变。
缺省两侧都用现行 V4 面板（即只换估值口径的情形）。

用法：
    python3 align_buy_line.py <基准逐日> [<待对齐逐日> ...] \
        --base-line 1.5853 --sell-line 1.10 --swap-margin 0.15 \
        --base-panel .../panel_moat_bank_v3.csv --panel .../panel_moat_bank_v4.csv

只换宇宙、估值文件不变时，两侧给同一个逐日文件即可。
"""
import argparse
import bisect
import collections
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIT = ROOT / "data/processed/pit_attention"
DEFAULT_PANEL = PIT / "panel_moat_bank_v4.csv"      # §9.7.1.2 的基准宇宙


def load_spans(panel: Path):
    spans = collections.defaultdict(list)
    with open(panel, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            spans[r["security_code"].zfill(6)].append((r["effective_from"], r["effective_to"]))
    return spans


def ratios(path: Path, spans) -> list[float]:
    """面板在册期内的全部 `P/V` 观测，升序。"""
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            code = r["security_code"].zfill(6)
            day = r["date"]
            if not any(a <= day < b for a, b in spans.get(code, ())):
                continue
            try:
                out.append(float(r["valuation_ratio"]))
            except (TypeError, ValueError):
                pass
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", type=Path, help="基准侧逐日估值状态")
    ap.add_argument("arms", type=Path, nargs="*", help="待对齐的逐日估值状态；只换宇宙时给同一个文件")
    ap.add_argument("--base-line", type=float, required=True, help="基准侧买入线")
    ap.add_argument("--sell-line", type=float, help="基准侧减持线，给了才对齐")
    ap.add_argument("--swap-margin", type=float, help="基准侧换仓最小改善，给了才按买入线比例缩放")
    ap.add_argument("--base-panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL, help="待对齐侧面板")
    a = ap.parse_args()

    base = ratios(a.base, load_spans(a.base_panel))
    if not base:
        raise SystemExit("基准侧在册观测为 0——面板与逐日文件对不上，先查代码位数与日期区间")
    buy_share = bisect.bisect_right(base, a.base_line) / len(base)
    print(f"基准 {a.base.name} × {a.base_panel.name}：在册观测 {len(base):,}")
    print(f"  买入线 {a.base_line:.4f} → 下侧合格面 {buy_share * 100:.3f}%")
    sell_share = None
    if a.sell_line is not None:
        sell_share = 1 - bisect.bisect_left(base, a.sell_line) / len(base)
        print(f"  减持线 {a.sell_line:.4f} → 上侧面 {sell_share * 100:.3f}%")

    arm_spans = load_spans(a.panel)
    for path in (a.arms or [a.base]):
        arm = ratios(path, arm_spans)
        if not arm:
            print(f"  {path.name}：在册观测为 0，跳过")
            continue
        buy = arm[min(int(buy_share * len(arm)), len(arm) - 1)]
        got = bisect.bisect_right(arm, buy) / len(arm)
        print(f"\n{path.name} × {a.panel.name}：在册观测 {len(arm):,}")
        print(f"  买入线 **{buy:.4f}**（`--width {1 - buy:.4f}`）→ 下侧合格面 {got * 100:.3f}%")
        if sell_share is not None:
            sell = arm[max(len(arm) - 1 - int(sell_share * len(arm)), 0)]
            got_s = 1 - bisect.bisect_left(arm, sell) / len(arm)
            print(f"  减持线 **{sell:.4f}**（`--sell-line {sell:.4f}`）→ 上侧面 {got_s * 100:.3f}%")
        if a.swap_margin is not None:
            print(f"  换仓改善 **{a.swap_margin * buy / a.base_line:.4f}**"
                  f"（`--swap-margin {a.swap_margin * buy / a.base_line:.4f}`，按买入线同倍缩放）")


if __name__ == "__main__":
    main()

"""线对齐（§12.30 / OI-045）：换宇宙或换估值口径后，重解回测对照臂的两条线。

`P/V` 的分布整体平移之后，同一条名义线放行的合格面完全不同，
比出来的是「两条不同宽度的闸门」而不是「两套设定」。
故对每条臂重解一条线，使**面板在册观测中落在线同侧的比例与基准相同**。

**两条线都要对齐，只对齐买入线会得到污染的比较**（§12.45 踩过一次）。
- **买入线**按「`P/V ≤ 线` 的比例」对齐（下侧分位）；
- **换仓最小改善**按买入线的缩放比例同倍缩放（它是 `P/V` 的差，不是分位）。

**基准侧与待对齐侧可以是不同的面板**——V3 → V4 那次正是宇宙变了而估值文件没变。
缺省两侧都用现行 V4 面板（即只换估值口径的情形）。

用法：
    python3 align_buy_line.py <基准逐日> [<待对齐逐日> ...] \
        --base-line 1.5853 --swap-margin 0.15 \
        --base-panel .../panel_moat_bank_v3.csv --panel .../panel_moat_bank_v4.csv

只换宇宙、估值文件不变时，两侧给同一个逐日文件即可。

**生产取值保留四位小数、不取整**（v4.34，用户 2026-08-21 裁定，回测日志 §12.102）：曾试把对齐解四舍五入到 0.01，
23 起点比对齐解低 0.72pp 滚5（4/23），用户以「损害年化」否决；本脚本打印的四位小数解直接落到 §9.3.1／`SEC93_*`／`BASE`。

**对齐容差**（v4.169，OI-168 用户 2026-09-09 裁定，工作流 §12.1）：新口径逐日状态上**原线**的下侧合格面与在册合格面之差
的绝对值 < `--tolerance-pp`（缺省 0.2pp）时保留原线、不重解；在册合格面不随之改写（仍取上次实际重解值，避免多次容差内
漂移累积）。OI-168 的教训：线只移 0.004（合格面差 0.157pp）就把 14 起点年化翻转 3.8pp，而 §12.178 量到买入线本身是
±2pp 的锯齿平台——容差内的重解只是把比较推进门槛噪声。`--registered-share` 可直接给在册合格面（百分数）作基准侧。
"""
import argparse
import bisect
import collections
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIT = ROOT / "data/processed/pit_attention"
DEFAULT_PANEL = PIT / "panel_moat_bank_v6b.csv"     # §9.3.1.2 的基准宇宙


def load_spans(panel: Path):
    spans = collections.defaultdict(list)
    with open(panel, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            spans[r["security_code"].zfill(6)].append(
                (r["effective_from"], r.get("effective_to") or "9999-12-31")
            )
    return spans


def ratios(path: Path, spans) -> list[float]:
    """面板在册期内的全部 `P/V` 观测，升序。"""
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            code = r["security_code"].zfill(6)
            day = r["date"]
            if not any(a <= day <= b for a, b in spans.get(code, ())):
                continue
            try:
                out.append(float(r["valuation_ratio"]))
            except (TypeError, ValueError):
                pass
    out.sort()
    return out


def resolve_line(arm: list[float], base_line: float, base_share: float,
                 tolerance_pp: float) -> tuple[float, float, float, bool]:
    """§12.1 对齐容差：返回 (取用线, 取用线合格面, 原线在本侧合格面, 是否保留原线)。

    `arm` 须升序；合格面按 `P/V ≤ 线` 的比例（下侧分位）。原线合格面与在册合格面之差的绝对值
    小于 `tolerance_pp`（百分点）时保留原线，否则取与在册合格面同分位的观测值（四位小数）。
    """
    old_share = bisect.bisect_right(arm, base_line) / len(arm)
    if abs(old_share - base_share) * 100 < tolerance_pp:
        return base_line, old_share, old_share, True
    line = round(arm[min(int(base_share * len(arm)), len(arm) - 1)], 4)
    return line, bisect.bisect_right(arm, line) / len(arm), old_share, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", type=Path, help="基准侧逐日估值状态")
    ap.add_argument("arms", type=Path, nargs="*", help="待对齐的逐日估值状态；只换宇宙时给同一个文件")
    ap.add_argument("--base-line", type=float, required=True, help="基准侧买入线")
    ap.add_argument("--swap-margin", type=float, help="基准侧换仓最小改善，给了才按买入线比例缩放（§12.1 现行：边际不缩放、按 0.01 一档重扫）")
    ap.add_argument("--base-panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL, help="待对齐侧面板")
    ap.add_argument("--tolerance-pp", type=float, default=0.2,
                    help="§12.1 对齐容差（百分点）：原线在新口径上的合格面与在册合格面之差的绝对值小于此值时保留原线")
    ap.add_argument("--registered-share", type=float,
                    help="在册合格面（百分数，如 17.771）；给了则作基准侧合格面，基准逐日文件只用于打印对照")
    a = ap.parse_args()

    base = ratios(a.base, load_spans(a.base_panel))
    if not base:
        raise SystemExit("基准侧在册观测为 0——面板与逐日文件对不上，先查代码位数与日期区间")
    measured = bisect.bisect_right(base, a.base_line) / len(base)
    buy_share = a.registered_share / 100 if a.registered_share is not None else measured
    print(f"基准 {a.base.name} × {a.base_panel.name}：在册观测 {len(base):,}")
    print(f"  买入线 {a.base_line:.4f} → 下侧合格面 {measured * 100:.3f}%"
          + (f"；在册合格面按 --registered-share 取 {buy_share * 100:.3f}%" if a.registered_share is not None else ""))
    print(f"  对齐容差 ±{a.tolerance_pp:.2f}pp")

    arm_spans = load_spans(a.panel)
    for path in (a.arms or [a.base]):
        arm = ratios(path, arm_spans)
        if not arm:
            print(f"  {path.name}：在册观测为 0，跳过")
            continue
        buy, got, old_share, kept = resolve_line(arm, a.base_line, buy_share, a.tolerance_pp)
        print(f"\n{path.name} × {a.panel.name}：在册观测 {len(arm):,}")
        print(f"  原线 {a.base_line:.4f} 在本侧的下侧合格面 {old_share * 100:.3f}%"
              f"（与在册差 {(old_share - buy_share) * 100:+.3f}pp）")
        if kept:
            print(f"  容差内 → **保留原线 {buy:.4f}**（`--width {1 - buy:.4f}`）；在册合格面不改写")
        else:
            print(f"  超出容差 → 买入线 **{buy:.4f}**（`--width {1 - buy:.4f}`）→ 下侧合格面 {got * 100:.3f}%，重登在册合格面")
        if a.swap_margin is not None:
            print(f"  换仓改善 **{a.swap_margin * buy / a.base_line:.4f}**"
                  f"（`--swap-margin {a.swap_margin * buy / a.base_line:.4f}`，按买入线同倍缩放；§12.1 现行不缩放、只作参考）")


if __name__ == "__main__":
    main()

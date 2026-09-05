"""剂量／边际档位裁定表：配对差 Δ 与各档水平中位并列（§12.176 末段的登记方式）。

读 `sweep_backtest_configs.py` 的 --out 扫描文件，对每条臂打印：
  Δ主(全)／Δ复利(全)／Δ主(去)／Δ复利(去)／ΔP25(全)／Δ滚5回撤(全)  ——逐起点配对差中位（pp）
  滚5中位／年化／滚5P25／滚5回撤／换手（全样本水平中位）＋ 去赢家的滚5中位／年化
  第 2 款判定（与 sweep 的【采纳判定】同一规则）
用法：python3 scripts/experimental/dose_table.py <扫描文件> [--sort 年化|滚5|label] [--pattern REGEX]
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sbc  # noqa: E402


def load(path: Path):
    """读扫描文件 → (全样本臂, 去赢家臂, 臂顺序)。解析走 `sweep_backtest_configs.load_scan`（按 `#METRIC` 首行
    或行宽识别计量版本）；版本与现行引擎不同只告警不中断，读数不得与现行 BASE 配对。"""
    groups, orders, _failed, _note, version, _fields = sbc.load_scan(path)
    if version != sbc.METRIC_VERSION:
        print(f"⚠ {path}：计量版本 {version}，现行 {sbc.METRIC_VERSION}，读数只读不配对", file=sys.stderr)
    return dict(groups[""]), dict(groups[sbc.EX5_PREFIX]), orders[""]


def paired(arms, label, key):
    base, arm = arms.get("BASE"), arms.get(label)
    if not base or not arm:
        return float("nan"), 0, 0
    common = [s for s in arm if s in base]
    d = [arm[s][key] - base[s][key] for s in common]
    return (statistics.median(d) if d else float("nan")), sum(1 for v in d if v > 0), len(d)


def level(arms, label, key):
    arm = arms.get(label) or {}
    v = [r[key] for r in arm.values()]
    return statistics.median(v) if v else float("nan")


def verdict(arms_all, arms_ex, label):
    if label not in arms_ex:
        return "去赢家缺表"
    vals = {}
    for name, key in sbc.VERDICT_KEYS:
        vals[name] = (paired(arms_all, label, key)[0], paired(arms_ex, label, key)[0])
    out, reasons = "可采纳", []
    for name, (a, e) in vals.items():
        lo, hi = min(a, e), max(a, e)
        if lo < -sbc.RULING_TOLERANCE:
            return f"不采纳（{name} {lo*100:+.2f}）"
        if lo < -sbc.NOISE_BAND:
            if hi >= sbc.CLEAR_GAIN and out != "不采纳":
                out, reasons = "报用户裁定", reasons + [f"{name}两表反向"]
            else:
                return f"不采纳（{name}一表 {lo*100:+.2f}）"
    base, arm = arms_all.get("BASE", {}), arms_all.get(label, {})
    common = [s for s in arm if s in base]
    if common:
        dd = statistics.median(arm[s]["滚动5年回撤中位"] - base[s]["滚动5年回撤中位"] for s in common)
        neg_up = sum(1 for s in common if arm[s]["滚动5年为负的窗口占比"] > base[s]["滚动5年为负的窗口占比"])
        if dd > sbc.DRAWDOWN_GATE:
            out, reasons = "不采纳", reasons + [f"闸门 回撤 {dd*100:+.1f}"]
        if neg_up > len(common) / 2:
            out, reasons = "不采纳", reasons + [f"否决 负窗↑{neg_up}/{len(common)}"]
    return out + (f"（{'；'.join(reasons)}）" if reasons else "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep", type=Path)
    ap.add_argument("--sort", choices=("年化", "滚5", "label"), default="label")
    ap.add_argument("--pattern", default="", help="只列标签匹配此正则的臂")
    args = ap.parse_args()
    arms_all, arms_ex, order = load(args.sweep)
    labels = [l for l in order if not args.pattern or re.search(args.pattern, l)]
    rows = []
    for l in labels:
        d5, s5, n = paired(arms_all, l, "滚动5年年化中位")
        dc, sc, _ = paired(arms_all, l, "年化")
        d5e, _, _ = paired(arms_ex, l, "滚动5年年化中位")
        dce, _, _ = paired(arms_ex, l, "年化")
        d25, _, _ = paired(arms_all, l, "滚动5年年化P25")
        ddd, _, _ = paired(arms_all, l, "滚动5年回撤中位")
        rows.append((l, d5, s5, dc, sc, d5e, dce, d25, ddd, n,
                     level(arms_all, l, "滚动5年年化中位"), level(arms_all, l, "年化"),
                     level(arms_all, l, "滚动5年年化P25"), level(arms_all, l, "滚动5年回撤中位"),
                     level(arms_all, l, "年均换手"),
                     level(arms_ex, l, "滚动5年年化中位"), level(arms_ex, l, "年化"),
                     "" if l == "BASE" else verdict(arms_all, arms_ex, l)))
    if args.sort == "年化":
        rows.sort(key=lambda r: (r[0] != "BASE", -(r[3] if r[3] == r[3] else -9)))
    elif args.sort == "滚5":
        rows.sort(key=lambda r: (r[0] != "BASE", -(r[1] if r[1] == r[1] else -9)))
    f = lambda x, w=8, p=2: f"{'—':>{w}}" if x != x else f"{x*100:>+{w}.{p}f}"
    g = lambda x, w=8, p=2, s=100: f"{'—':>{w}}" if x != x else f"{x*s:>{w}.{p}f}"
    print(f"{'臂':<24}{'Δ主(全)':>8}{'符':>6}{'Δ复利(全)':>9}{'符':>6}{'Δ主(去)':>8}{'Δ复利(去)':>9}{'ΔP25':>8}{'Δ滚5回撤':>9}"
          f"{'|滚5中位':>9}{'年化':>8}{'滚5P25':>8}{'滚5回撤':>8}{'换手':>6}{'|去:滚5':>8}{'去:年化':>8}  判定")
    for (l, d5, s5, dc, sc, d5e, dce, d25, ddd, n, L5, Lc, L25, Ld, Lt, E5, Ec, v) in rows:
        print(f"{l:<24}{f(d5)}{f'{s5}/{n}':>6}{f(dc, 9)}{f'{sc}/{n}':>6}{f(d5e)}{f(dce, 9)}{f(d25)}{f(ddd, 9)}"
              f"{g(L5, 9)}{g(Lc)}{g(L25)}{g(Ld, 8, 1)}{g(Lt, 6, 2, 1)}{g(E5)}{g(Ec)}  {v}")


if __name__ == "__main__":
    main()

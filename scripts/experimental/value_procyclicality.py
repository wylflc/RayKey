#!/usr/bin/env python3
"""内在价值的顺周期读数（OI-115）：逐年 Spearman(过去 1 年 `V` 变动, 过去 1 年价格变动)。

`ρ > 0` = 内在价值跟着价格走，`ρ ≈ 0` = 带给价格提供独立的锚。
§1 执行原则 2 要求「合理价区间只由基本面证据与模型改变」，故该读数是 OI-115 的机制层判据；
它不是 §12.1 第 2 款的决策读数，两者分列、不得互相替代。

**观测取月末**：每个代码每个自然月取最后一条状态行，与去年同月末配对（不足 11 个月或
超过 13 个月的配对丢弃）。给 `--panel` 时只取面板在册期内的观测。

**除权复权**：逐日状态里的 `close` 不复权、`intrinsic_value` 已按除权事件折到当日股本基准，
两者同基。直接取两个日期的比值会让 10 转 10 在**两边同时**造出 −50%、每一笔现金分红在两边
各造一次下跳，跨股票拼成假的正相关。故把**上一期的价与 V 一起**按 `exright_adjust`
（交易所除权参考价公式 `v → (v − 现金 + 配股款) ÷ (1 + 送转 + 配股)`，即建带器折算 V 用的同一个函数、
同一份除权事件表）复权到本期股本口径后再比：

    (P₀', V₀') = exright_adjust(actions, 上期日, 本期日, (P₀, V₀))
    Δln P = ln(P_t / P₀')      Δln V = ln(V_t / V₀')

两边逐事件同式同参，送转、现金分红与配股都不再在任一侧留下假变动。

另报三项辅助量（判「带动了没有、动多大」，用于分辨「ρ 降低」是真的解耦还是把带冻住）：
`|Δln V|` 中位、`V` 完全不动（|Δln V| ≤ 0.001）的观测占比、`Δln V` 的正负号占比。

用法：
    python3 scripts/experimental/value_procyclicality.py \\
        --states data/processed/a_share_daily_states_adopted.csv \\
        --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --label BASE

多臂一次比较（表尾出逐年对照）：
    python3 scripts/experimental/value_procyclicality.py --panel ... \\
        --states BASE=.../states_BASE.csv --states TW00=.../states_TW00.csv
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_historical_valuation_bands as bhv  # noqa: E402
from moat_param_lab import spearman  # noqa: E402


def load_spans(path: Path) -> dict[str, list[tuple[str, str]]]:
    spans: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            spans[r["security_code"].zfill(6)].append(
                (r["effective_from"], r.get("effective_to") or "9999-12-31"))
    return dict(spans)


def month_ends(path: Path, spans: dict | None) -> dict[str, dict[str, tuple[str, float, float]]]:
    """流式扫一遍：{代码: {年月: (日期, close, V)}}，每月取最后一条在册行。"""
    out: dict[str, dict[str, tuple[str, float, float]]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        i_code, i_date = header.index("security_code"), header.index("date")
        i_close, i_v = header.index("close"), header.index("intrinsic_value")
        for row in reader:
            code = row[i_code].zfill(6)
            if spans is not None and code not in spans:
                continue
            day = row[i_date]
            if spans is not None and not any(a <= day <= b for a, b in spans[code]):
                continue
            try:
                close, value = float(row[i_close]), float(row[i_v])
            except (TypeError, ValueError):
                continue
            if close <= 0 or value <= 0:
                continue
            out[code][day[:7]] = (day, close, value)
    return out


def prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1:04d}-{m:02d}"


def pairs(states: dict, actions: dict, adjust: bool = True) -> list[tuple[str, str, float, float]]:
    """[(年月, 代码, Δln 价, Δln V)]，缺省已把上一期的价与 V 一起复权到本期股本口径。

    `adjust=False` 复现未复权口径（回测日志 §12.144 首登值即此口径）：10 转 10 让 `close`
    与 `intrinsic_value` **同时**掉一半，跨股票拼成假的正相关，ρ 因此约翻倍。只作复现，不作依据。
    """
    out = []
    from math import log
    dropped = 0
    for code, by_month in states.items():
        acts = actions.get(code, [])
        for ym, (day, close, value) in by_month.items():
            back = by_month.get(prev_month(ym))
            if not back:
                continue
            day0, close0, value0 = back
            gap = (date.fromisoformat(day) - date.fromisoformat(day0)).days
            if not 330 <= gap <= 400:
                continue
            if adjust:
                (close0, value0), _f, _c = bhv.exright_adjust(acts, day0, day, (close0, value0))
            if close0 <= 0 or value0 <= 0:      # 分红超过当时价／带值：复权后无意义，丢弃并计数（§13 第 3 条）
                dropped += 1
                continue
            out.append((ym, code, log(close / close0), log(value / value0)))
    if dropped:
        print(f"  （复权后价或 V ≤ 0 而丢弃的配对：{dropped}）")
    return out


def summarize(rows: list[tuple[str, str, float, float]], split_year: str
              ) -> tuple[list[tuple[str, int, float | None]], dict]:
    by_year: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for ym, _code, dp, dv in rows:
        by_year[ym[:4]].append((dp, dv))
    per_year = []
    for year in sorted(by_year):
        obs = by_year[year]
        rho = spearman([p for p, _ in obs], [v for _, v in obs]) if len(obs) >= 20 else None
        per_year.append((year, len(obs), rho))
    got = [(y, r) for y, _n, r in per_year if r is not None]
    early = [r for y, r in got if y < split_year]
    late = [r for y, r in got if y >= split_year]
    dv = [v for _ym, _c, _p, v in rows]
    aux = {
        "n": len(rows),
        "years_positive": sum(1 for _y, r in got if r > 0),
        "years": len(got),
        "rho_all": statistics.median([r for _y, r in got]) if got else None,
        "rho_early": statistics.median(early) if early else None,
        "rho_late": statistics.median(late) if late else None,
        "rho_min": min((r for _y, r in got), default=None),
        "rho_max": max((r for _y, r in got), default=None),
        "abs_dv_median": statistics.median([abs(v) for v in dv]) if dv else None,
        "frozen_share": (sum(1 for v in dv if abs(v) <= 0.001) / len(dv)) if dv else None,
        "up_share": (sum(1 for v in dv if v > 0) / len(dv)) if dv else None,
    }
    return per_year, aux


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", action="append", required=True, metavar="[标签=]文件",
                    help="逐日估值状态；可重复给多臂，写成 `标签=路径` 即按标签命名")
    ap.add_argument("--panel", type=Path, help="股票库面板；给了就只取在册期观测")
    ap.add_argument("--split", default="2017", help="早/晚纪元分界年（含），缺省 2017")
    ap.add_argument("--since", default="", help="只取该年月及之后的观测（如 2005-01）")
    ap.add_argument("--label", help="单臂时的标签（等价于 `标签=路径`）")
    ap.add_argument("--no-split-adjust", action="store_true",
                    help="不按累计送转因子折算（复现 §12.144 首登口径，ρ 含送转假相关，只作复现）")
    args = ap.parse_args()

    spans = load_spans(args.panel) if args.panel else None
    actions = bhv.load_actions()
    arms = []
    for i, spec in enumerate(args.states):
        label, _, path = spec.partition("=")
        if not path:
            label, path = (args.label or f"ARM{i}"), spec
        arms.append((label, Path(path)))

    print(f"内在价值顺周期读数（OI-115 机制层）｜面板 {args.panel.name if args.panel else '全市场'}"
          f"｜纪元分界 {args.split}"
          f"｜送转{'不折算（§12.144 首登口径，含假相关）' if args.no_split_adjust else '已折算'}")
    print("  ρ = 逐年 Spearman(Δln 价, Δln V)，月末观测与去年同月末配对；ρ>0 = 带跟着价格走\n")

    table: dict[str, dict[str, float | None]] = {}
    counts: dict[str, int] = {}
    auxes = {}
    for label, path in arms:
        rows = pairs(month_ends(path, spans), actions, adjust=not args.no_split_adjust)
        if args.since:
            rows = [r for r in rows if r[0] >= args.since]
        per_year, aux = summarize(rows, args.split)
        auxes[label] = aux
        for year, n, rho in per_year:
            table.setdefault(year, {})[label] = rho
            counts[year] = max(counts.get(year, 0), n)      # 各臂观测数只差被拒绝的带，取最大作规模参考

    labels = [lab for lab, _ in arms]
    years = sorted(table)
    width = max(10, max(len(lab) for lab in labels) + 2)
    print("  " + "年".ljust(6) + "观测".rjust(8) + "".join(lab.rjust(width) for lab in labels))
    for year in years:
        cells = "".join((f"{table[year][lab]:+.3f}" if table[year].get(lab) is not None else "—").rjust(width)
                        for lab in labels)
        print("  " + year.ljust(6) + f"{counts[year]:,}".rjust(8) + cells)
    print("  " + "-" * (14 + width * len(labels)))
    for name, key, fmt in (("ρ 中位·全期", "rho_all", "{:+.3f}"), (f"ρ 中位·<{args.split}", "rho_early", "{:+.3f}"),
                           (f"ρ 中位·≥{args.split}", "rho_late", "{:+.3f}"),
                           ("ρ 最小", "rho_min", "{:+.3f}"), ("ρ 最大", "rho_max", "{:+.3f}")):
        print("  " + name.ljust(14) + "".join(
            (fmt.format(auxes[lab][key]) if auxes[lab][key] is not None else "—").rjust(width) for lab in labels))
    print("  " + "为正的年数".ljust(14) + "".join(
        f"{auxes[lab]['years_positive']}/{auxes[lab]['years']}".rjust(width) for lab in labels))
    print("  " + "|ΔlnV| 中位".ljust(14) + "".join(
        f"{auxes[lab]['abs_dv_median']:.4f}".rjust(width) for lab in labels))
    print("  " + "V 冻结占比".ljust(14) + "".join(
        f"{auxes[lab]['frozen_share'] * 100:.1f}%".rjust(width) for lab in labels))
    print("  " + "ΔlnV>0 占比".ljust(14) + "".join(
        f"{auxes[lab]['up_share'] * 100:.1f}%".rjust(width) for lab in labels))
    print("  " + "配对观测".ljust(14) + "".join(f"{auxes[lab]['n']:,}".rjust(width) for lab in labels))


if __name__ == "__main__":
    main()

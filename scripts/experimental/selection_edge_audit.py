#!/usr/bin/env python3
"""选择环节的信息量审计（L2 信号层：`docs/000_Ashare_workflow.md` §12.1 第 9 款）。

回测的路径读数（滚 5 中位等）由少数复利段主导，臂间差异常常只反映「谁更妥善地
碰到了那几个赢家」。本脚本改问一个不依赖赢家身份、样本量大三个量级的问题：

    **在同一天同样够格的候选里，被选中的那批其后是否真的比没被选中的那批好？**

三张表：

* 表 1 **边际选择检验**——同日合格集里「买到的」对「没买到的」前向总回报。
  这是排序＋相关性过滤＋资金分配三者合起来的边际信息量。零假设为真时，
  臂间比较测的就是被复利放大的抛硬币。
* 表 2 **排序信息量**——合格集名次（rank 1 / 2-5 / 6-10）对前向总回报的单调性。
  只测排序本身，不含资金分配。
* 表 3 **换仓的方向性**——同日「换仓卖出源」对「换仓买入目标」的前向总回报配对。
  换仓的全部理由是把钱押回更便宜的档，这张表检验该动作事后是否成立。

**统计口径**：同一天的多个候选强相关（同一市场状态、常同一行业），故一律
**先在日内取中位、再跨日汇总**——报「逐日配对差的中位数」与「为正的日数」，
而不是把所有观测倒进一个池子。跨日仍有前向窗口重叠，故另报逐年分解：
结论要求在多数年份同号，而不是靠某一两年撑起来。

前向回报含现金分红再投（`total_return_index`），与 `moat_param_lab.py` 同口径。

用法::

    # 1) 先跑一次带两份日志的回测（BASE 全参数见 sweep_backtest_configs.py 的 BASE）
    python3 scripts/backtest_valuation_strategy.py <BASE 全参数> --since 2011-11-01 \
        --candidate-log /path/cand.csv --trade-log /path/trades.csv --out-dir /path/bt

    # 2) 审计
    python3 scripts/experimental/selection_edge_audit.py \
        --candidate-log /path/cand.csv --trade-log /path/trades.csv --horizon 250
"""
from __future__ import annotations

import argparse
import bisect
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_historical_valuation_bands as bhv  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402


def forward_return(tr: dict[str, float], days: list[str], start: str, n: int) -> float | None:
    """自 `start` 起 `n` 个交易日的总回报；不足整段返回 None。"""
    i = bisect.bisect_left(days, start)
    if i >= len(days) or days[i] != start or i + n >= len(days):
        return None
    base = tr.get(days[i])
    end = tr.get(days[i + n])
    if not base or end is None or base <= 0:
        return None
    return end / base - 1.0


def build_returns(codes: set[str]) -> dict[str, tuple[dict[str, float], list[str]]]:
    """逐票总回报指数与交易日序列（与 `panel_tier_forward.py` 同一读法）。"""
    actions = bhv.load_actions()
    out = {}
    for code in sorted(codes):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        out[code] = (total_return_index(prices, actions.get(code, [])), [d for d, _ in prices])
    return out


def daily_paired(groups: dict[str, tuple[list[float], list[float]]]) -> dict:
    """逐日先取组内中位、再跨日汇总配对差。groups: day -> (处理组样本, 对照组样本)。"""
    diffs, days_used = [], []
    for day in sorted(groups):
        a, b = groups[day]
        if not a or not b:
            continue
        diffs.append(statistics.median(a) - statistics.median(b))
        days_used.append(day)
    if not diffs:
        return {"n_days": 0}
    pos = sum(1 for d in diffs if d > 0)
    return {"n_days": len(diffs), "median": statistics.median(diffs),
            "mean": statistics.fmean(diffs), "pos": pos,
            "pos_rate": pos / len(diffs), "days": days_used, "diffs": diffs}


def by_year(days_used: list[str], diffs: list[float]) -> list[tuple[str, int, float, float]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for d, v in zip(days_used, diffs):
        buckets[d[:4]].append(v)
    return [(y, len(v), statistics.median(v), sum(1 for x in v if x > 0) / len(v))
            for y, v in sorted(buckets.items())]


def fmt_pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%"


def print_block(title: str, res: dict, note: str = "") -> None:
    print(f"\n{title}")
    if not res.get("n_days"):
        print("  样本不足")
        return
    print(f"  逐日配对差中位 {fmt_pct(res['median'])}   均值 {fmt_pct(res['mean'])}   "
          f"为正 {res['pos']}/{res['n_days']} = {res['pos_rate']:.1%}")
    if note:
        print(f"  {note}")
    rows = by_year(res["days"], res["diffs"])
    print("  逐年：" + "  ".join(f"{y}:{fmt_pct(m)}({n})" for y, n, m, _ in rows))
    pos_years = sum(1 for _, _, m, _ in rows if m > 0)
    print(f"  年度同号：{pos_years}/{len(rows)} 年为正")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-log", type=Path, required=True)
    ap.add_argument("--trade-log", type=Path, required=True)
    ap.add_argument("--horizon", type=int, default=250, help="前向交易日数，缺省 250（≈1 年）")
    ap.add_argument("--max-rank", type=int, default=10)
    args = ap.parse_args()

    # ---- 读候选日志：(exec_date, code) -> (rank, pv, held)
    cand: dict[tuple[str, str], tuple[int, float, int]] = {}
    with args.candidate_log.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rank = int(r["rank"])
            if rank > args.max_rank:
                continue
            cand[(r["exec_date"], r["security_code"])] = (rank, float(r["pv"]), int(r["held"]))

    # ---- 读成交流水：当日买入集合、换仓卖出源、换仓买入目标
    bought: set[tuple[str, str]] = set()
    swap_sell: dict[str, list[str]] = defaultdict(list)
    swap_buy: dict[str, list[str]] = defaultdict(list)
    swap_pairs: set[tuple[str, str]] = set()
    with args.trade_log.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            day, code, action = r["date"], r["security_code"], r["action"]
            reason = r.get("reason", "")
            if action == "买入":
                bought.add((day, code))
            elif action == "卖出" and "换仓" in reason:
                swap_sell[day].append(code)
                if "让位给" in reason:
                    target = reason.split("让位给")[-1].strip()
                    target = "".join(ch for ch in target if ch.isdigit())[:6]
                    if len(target) == 6:
                        swap_buy[day].append(target)
                        swap_pairs.add((code, target))

    codes = {c for _, c in cand} | {c for v in swap_sell.values() for c in v} \
        | {c for v in swap_buy.values() for c in v}
    print(f"读入：候选观测 {len(cand):,}（rank ≤ {args.max_rank}）、买入 {len(bought):,} 笔、"
          f"换仓卖出 {sum(len(v) for v in swap_sell.values()):,} 笔、涉及 {len(codes):,} 只")
    rets = build_returns(codes)
    print(f"取到行情的：{len(rets):,} 只；前向窗口 {args.horizon} 个交易日")

    # ---- 表 1：边际选择检验（只看新建仓，held=0）
    g_new: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    g_rank: dict[int, list[float]] = defaultdict(list)
    for (day, code), (rank, pv, held) in cand.items():
        if code not in rets:
            continue
        tr, days = rets[code]
        fr = forward_return(tr, days, day, args.horizon)
        if fr is None:
            continue
        g_rank[rank].append(fr)
        if held:
            continue
        picked, skipped = g_new[day]
        (picked if (day, code) in bought else skipped).append(fr)

    res1 = daily_paired(g_new)
    print_block(f"表 1　边际选择检验（合格集内 held=0：买到的 − 没买到的，前向 {args.horizon} 日总回报）",
                res1, "零假设：选择无信息 → 差为 0。为正说明排序＋过滤＋资金分配合起来确有边际信息量。")

    # ---- 表 2：排序信息量
    print(f"\n表 2　排序信息量（合格集名次 → 前向 {args.horizon} 日总回报，全部观测）")
    print(f"  {'名次':<8}{'样本':>8}{'中位':>10}{'均值':>10}{'为正':>9}")
    for lo, hi, label in ((1, 1, "rank 1"), (2, 5, "rank 2-5"), (6, 10, "rank 6-10")):
        pool = [v for k in range(lo, hi + 1) for v in g_rank.get(k, [])]
        if not pool:
            continue
        print(f"  {label:<8}{len(pool):>8,}{fmt_pct(statistics.median(pool)):>10}"
              f"{fmt_pct(statistics.fmean(pool)):>10}"
              f"{sum(1 for v in pool if v > 0) / len(pool):>9.1%}")

    # ---- 表 3：换仓方向性（同日 卖出源 vs 买入目标）
    g_swap: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for day in sorted(set(swap_sell) | set(swap_buy)):
        for code in swap_buy.get(day, []):
            if code in rets and (fr := forward_return(*rets[code], day, args.horizon)) is not None:
                g_swap[day][0].append(fr)
        for code in swap_sell.get(day, []):
            if code in rets and (fr := forward_return(*rets[code], day, args.horizon)) is not None:
                g_swap[day][1].append(fr)
    res3 = daily_paired(g_swap)
    # `换仓·减一档` 每天只卖一档，同一 (源, 标的) 会连着好几周重复出现：不同配对数才是
    # 表 3「日数」的有效上界。对照组见 `swap_regime_control.py`。
    print_block(f"表 3　换仓方向性（同日：换入目标 − 换出源，前向 {args.horizon} 日总回报）",
                res3, f"换仓的全部理由是把钱押回更便宜的档；为正说明该动作事后成立。\n"
                      f"  独立性：{sum(len(v) for v in swap_sell.values()):,} 笔换仓只有 "
                      f"{len(swap_pairs):,} 个不同 (源, 标的) 配对、"
                      f"{len({c for v in swap_sell.values() for c in v}):,} 个源、"
                      f"{len({c for v in swap_buy.values() for c in v}):,} 个标的。")

    print("\n口径提示：日内先取中位再跨日汇总，故「为正日数」不是独立样本数（前向窗口重叠）；"
          "\n结论以「逐年同号」为准，单一年份撑起来的差值不作证据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

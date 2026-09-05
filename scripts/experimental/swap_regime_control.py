#!/usr/bin/env python3
"""换仓方向性（`selection_edge_audit.py` 表 3）的对照组。

表 3 单独看不出结论：换仓的动作就是「卖掉 `P/V` 最高的持仓、买入 `P/V` 最低的候选」，
所以它的符号同时受两件事支配——

1. **信号纪元**：面板层「便宜的其后是否真的更好」本身逐年在变号；
2. **名字**：策略当时恰好持有和买到了谁。

只有把第 1 项作为对照扣掉，剩下的才是换仓机制自身的读数。本脚本出四张表：

* 表 A **面板层 `P/V` 信息量**——逐年 Spearman(`P/V`, 前向总回报) 与最便宜/最贵三分位价差，
  月末观测、只取在册期，完全不引用策略持仓。Spearman 为负 = 便宜的其后更好 = `P/V` 有效。
* 表 B **合成换仓**——同样只在面板上，按固定 `P/V` 档「买 `[--buy-lo, --buy-hi)`、
  卖 `[--sell-lo, --sell-hi)`」构造价差。这是没有排序、没有相关性过滤、没有资金分配的
  换仓，用来看表 3 的纪元分界有多少是信号纪元本身。
* 表 C **`P/V` 匹配对照**——逐笔换仓与「同日、同 `P/V` 水平（±`--tol`）的在册面板名字」比：
  买腿超额 = 换入目标 − 同 `P/V` 对照中位，卖腿超额 = 换出源 − 同 `P/V` 对照中位。
  买腿对照取候选侧状态、卖腿对照取持仓侧状态，各按自己那侧的口径匹配。
  超额 = 买腿超额 − 卖腿超额，即扣掉估值水平与纪元后换仓还剩多少。
* 表 D **样本独立性**——换仓笔数、不同 `(卖出源, 买入目标)` 配对数、不同源/标的数。
  `换仓·减一档` 每天只卖一档，同一配对会连着好几周重复出现，故「日数」远不是观测数。

统计口径与 `selection_edge_audit.py` 一致：日内先取中位、再跨日汇总；前向回报含现金
分红再投（`total_return_index`）；结论以逐年同号为准。

用法::

    python3 scripts/experimental/swap_regime_control.py \\
        --candidate-log data/experiments/exp_selection_edge/candidates.csv \\
        --trade-log data/experiments/exp_selection_edge/trades_ledger.csv \\
        --states data/processed/a_share_daily_states_adopted.csv \\
        --hold-states data/processed/a_share_daily_states_hold.csv \\
        --panel data/processed/pit_attention/panel_moat_bank_v6b.csv \\
        --split 2017

两份逐日状态各扫一遍（各 2.1~2.2 GB），本机约 3~5 分钟；连同建带链一起跑时按
`CLAUDE.md` 提交 sbatch。
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
from moat_param_lab import spearman, total_return_index  # noqa: E402


def load_spans(path: Path) -> dict[str, list[tuple[str, str]]]:
    spans: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            spans[r["security_code"].zfill(6)].append(
                (r["effective_from"], r.get("effective_to") or "9999-12-31"))
    return dict(spans)


def read_swaps(path: Path) -> list[tuple[str, str, str]]:
    """成交流水里的换仓：`(日期, 换出源, 换入目标)`。"""
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            reason = r.get("reason", "")
            if r["action"] != "卖出" or "换仓" not in reason or "让位给" not in reason:
                continue
            tgt = "".join(c for c in reason.split("让位给")[-1] if c.isdigit())[:6]
            if len(tgt) == 6:
                out.append((r["date"], r["security_code"], tgt))
    return out


def scan_states(path: Path, spans: dict, days_wanted: set[str], month_end: bool
                ) -> tuple[dict[str, dict[str, float]], dict[str, tuple[str, float]]]:
    """流式扫一遍逐日状态：返回 (换仓日 -> 代码 -> P/V, 代码 -> 月末 (日期, P/V))。

    月末取每个自然月该代码的最后一条；只留面板代码，在册判定留到调用方。
    """
    on_days: dict[str, dict[str, float]] = defaultdict(dict)
    month: dict[str, dict[str, tuple[str, float]]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        i_code, i_date, i_pv = (header.index("security_code"), header.index("date"),
                                header.index("valuation_ratio"))
        for row in reader:
            code = row[i_code].zfill(6)
            if code not in spans or not row[i_pv]:
                continue
            day = row[i_date]
            pv = float(row[i_pv])
            if day in days_wanted:
                on_days[day][code] = pv
            if month_end:
                month[code][day[:7]] = (day, pv)
    return on_days, month


def build_returns(codes, horizons):
    """逐票总回报指数、交易日序列与前向回报查表。"""
    actions = bhv.load_actions()
    tr_map, fwd_map = {}, {}
    for code in sorted(codes):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        tr = total_return_index(prices, actions.get(code, []))
        days = [d for d, _ in prices]
        tr_map[code] = (tr, days)
        cache: dict[tuple[str, int], float | None] = {}
        fwd_map[code] = (tr, days, cache)
    return tr_map, fwd_map


def make_fwd(fwd_map, horizon):
    def fwd(code: str, day: str):
        entry = fwd_map.get(code)
        if entry is None:
            return None
        tr, days, cache = entry
        key = (day, horizon)
        if key in cache:
            return cache[key]
        i = bisect.bisect_left(days, day)
        val = None
        if i < len(days) and days[i] == day and i + horizon < len(days):
            base, end = tr.get(days[i]), tr.get(days[i + horizon])
            if base and end is not None and base > 0:
                val = end / base - 1.0
        cache[key] = val
        return val
    return fwd


def pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%"


def med(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def epoch_rows(by_year: dict[str, list], split: str):
    lo = min(by_year) if by_year else "0000"
    hi = max(by_year) if by_year else "9999"
    return (("早期", lo, f"{int(split) - 1:04d}"), ("后期", split, hi))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-log", type=Path, required=True)
    ap.add_argument("--trade-log", type=Path, required=True)
    ap.add_argument("--states", type=Path, required=True, help="候选侧逐日状态")
    ap.add_argument("--hold-states", type=Path, required=True, help="持仓侧逐日状态")
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--horizon", type=int, default=250)
    ap.add_argument("--split", default="2017", help="纪元分界年（含）")
    ap.add_argument("--since", help="表 A/B 的起始日；缺省与最早一笔换仓同年，使四张表同窗口")
    ap.add_argument("--tol", type=float, default=0.06, help="表 C 的 P/V 匹配容差")
    ap.add_argument("--min-cohort", type=int, default=2, help="表 C 每侧最少对照只数")
    ap.add_argument("--buy-lo", type=float, default=0.40)
    ap.add_argument("--buy-hi", type=float, default=0.60)
    ap.add_argument("--sell-lo", type=float, default=0.70)
    ap.add_argument("--sell-hi", type=float, default=0.90)
    a = ap.parse_args()
    H = a.horizon

    spans = load_spans(a.panel)
    inforce = lambda c, d: any(lo <= d <= hi for lo, hi in spans.get(c, []))  # noqa: E731
    swaps = read_swaps(a.trade_log)
    swap_days = {d for d, _, _ in swaps}
    cand_pv = {}
    with a.candidate_log.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cand_pv[(r["exec_date"], r["security_code"])] = float(r["pv"])
    since = a.since or (min(swap_days)[:4] + "-01-01" if swap_days else "0000-01-01")
    print(f"换仓 {len(swaps)} 笔、{len(swap_days)} 个交易日；面板 {len(spans)} 只；"
          f"前向 {H} 日；表 A/B 自 {since}")

    print("扫描候选侧逐日状态…", flush=True)
    pv_cand_day, pv_month = scan_states(a.states, spans, swap_days, month_end=True)
    print("扫描持仓侧逐日状态…", flush=True)
    pv_hold_day, _ = scan_states(a.hold_states, spans, swap_days, month_end=False)

    codes = set(pv_month) | {c for v in pv_cand_day.values() for c in v} \
        | {c for v in pv_hold_day.values() for c in v} | {c for _, s, t in swaps for c in (s, t)}
    tr_map, fwd_map = build_returns(codes, (H,))
    fwd = make_fwd(fwd_map, H)
    print(f"取到行情 {len(tr_map)}/{len(codes)} 只\n")

    # ---------------- 表 A：面板层 P/V 信息量
    obs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for code, months in pv_month.items():
        for m, (day, pv) in months.items():
            if day < since or not inforce(code, day):
                continue
            f = fwd(code, day)
            if f is not None:
                obs[m].append((pv, f))
    rho_y, sp_y, n_y = defaultdict(list), defaultdict(list), defaultdict(list)
    for m, v in sorted(obs.items()):
        if len(v) < 10:
            continue
        rho_y[m[:4]].append(spearman([x for x, _ in v], [y for _, y in v]))
        s = sorted(v)
        k = max(1, len(s) // 3)
        sp_y[m[:4]].append(statistics.median([y for _, y in s[:k]])
                           - statistics.median([y for _, y in s[-k:]]))
        n_y[m[:4]].append(len(v))
    print(f"表 A　面板层 `P/V` 信息量（月末在册观测，前向 {H} 日）")
    print("  Spearman 为负 = 便宜的其后更好；三分位价差 = 最便宜 1/3 中位 − 最贵 1/3 中位")
    print(f"  {'年':<6}{'可比月':>6}{'样本/月':>8}{'Spearman':>10}{'三分位价差':>12}")
    for y in sorted(rho_y):
        print(f"  {y:<6}{len(rho_y[y]):>6}{statistics.median(n_y[y]):>8.0f}"
              f"{statistics.median(rho_y[y]):>10.3f}{pct(statistics.median(sp_y[y])):>12}")
    for label, lo, hi in epoch_rows(rho_y, a.split):
        r = [x for y in rho_y for x in rho_y[y] if lo <= y <= hi]
        s = [x for y in sp_y for x in sp_y[y] if lo <= y <= hi]
        if r:
            print(f"  {label} {lo}-{hi}　Spearman 中位 {statistics.median(r):+.3f}　"
                  f"为负月 {sum(1 for x in r if x < 0) / len(r):.0%}　"
                  f"三分位价差中位 {pct(statistics.median(s))}")

    # ---------------- 表 B：合成换仓
    band = lambda v, lo, hi: [f for pv, f in v if lo <= pv < hi]  # noqa: E731
    syn: dict[str, list[float]] = defaultdict(list)
    for m, v in sorted(obs.items()):
        b, s = band(v, a.buy_lo, a.buy_hi), band(v, a.sell_lo, a.sell_hi)
        if len(b) >= 3 and len(s) >= 3:
            syn[m[:4]].append(statistics.median(b) - statistics.median(s))
    print(f"\n表 B　合成换仓（面板月末：买 [{a.buy_lo:.2f},{a.buy_hi:.2f})　"
          f"卖 [{a.sell_lo:.2f},{a.sell_hi:.2f})；不引用任何持仓）")
    print(f"  {'年':<6}{'可比月':>6}{'价差中位':>10}{'为正月':>8}")
    for y in sorted(syn):
        print(f"  {y:<6}{len(syn[y]):>6}{pct(statistics.median(syn[y])):>10}"
              f"{sum(1 for x in syn[y] if x > 0) / len(syn[y]):>8.0%}")
    for label, lo, hi in epoch_rows(syn, a.split):
        g = [x for y in syn for x in syn[y] if lo <= y <= hi]
        yrs = [y for y in syn if lo <= y <= hi]
        if g:
            print(f"  {label} {lo}-{hi}　价差中位 {pct(statistics.median(g))}　"
                  f"为正月 {sum(1 for x in g if x > 0) / len(g):.0%}　逐年为正 "
                  f"{sum(1 for y in yrs if statistics.median(syn[y]) > 0)}/{len(yrs)} 年")

    # ---------------- 表 C：P/V 匹配对照
    def cohort(day: str, pv0: float, exclude: str, side: dict) -> list[float]:
        out = []
        for code, pv in side.get(day, {}).items():
            if code == exclude or abs(pv - pv0) > a.tol or not inforce(code, day):
                continue
            f = fwd(code, day)
            if f is not None:
                out.append(f)
        return out

    d_act, d_buy, d_sell = defaultdict(list), defaultdict(list), defaultdict(list)
    used, skipped = 0, 0
    for day, src, tgt in swaps:
        spv = pv_hold_day.get(day, {}).get(src)
        tpv = cand_pv.get((day, tgt))
        f_t, f_s = fwd(tgt, day), fwd(src, day)
        if spv is None or tpv is None or f_t is None or f_s is None:
            skipped += 1
            continue
        ct = cohort(day, tpv, tgt, pv_cand_day)
        cs = cohort(day, spv, src, pv_hold_day)
        if len(ct) < a.min_cohort or len(cs) < a.min_cohort:
            skipped += 1
            continue
        d_act[day].append(f_t - f_s)
        d_buy[day].append(f_t - statistics.median(ct))
        d_sell[day].append(f_s - statistics.median(cs))
        used += 1
    print(f"\n表 C　`P/V` 匹配对照（容差 ±{a.tol}，每侧至少 {a.min_cohort} 只）"
          f"　可比 {used} 笔、弃 {skipped} 笔")
    print(f"  {'年':<6}{'日数':>5}{'实际差':>10}{'买腿超额':>10}{'卖腿超额':>10}{'合计超额':>10}{'超额为正日':>11}")
    years = sorted({d[:4] for d in d_act})
    per_year = {}
    for y in years:
        ds = [d for d in d_act if d[:4] == y]
        act = med([med(d_act[d]) for d in ds])
        buy = med([med(d_buy[d]) for d in ds])
        sell = med([med(d_sell[d]) for d in ds])
        exc = [med(d_buy[d]) - med(d_sell[d]) for d in ds]
        per_year[y] = (len(ds), act, buy, sell, med(exc),
                       sum(1 for x in exc if x > 0) / len(exc))
        n, ac, b, s, e, p = per_year[y]
        print(f"  {y:<6}{n:>5}{pct(ac):>10}{pct(b):>10}{pct(s):>10}{pct(e):>10}{p:>11.0%}")
    for label, lo, hi in epoch_rows({y: 1 for y in years}, a.split):
        ds = [d for d in d_act if lo <= d[:4] <= hi]
        yrs = [y for y in years if lo <= y <= hi]
        if not ds:
            continue
        exc = [med(d_buy[d]) - med(d_sell[d]) for d in ds]
        print(f"  {label} {lo}-{hi}　日 {len(ds)}　实际 {pct(med([med(d_act[d]) for d in ds]))}"
              f"　买腿超额 {pct(med([med(d_buy[d]) for d in ds]))}"
              f"　卖腿超额 {pct(med([med(d_sell[d]) for d in ds]))}"
              f"　合计超额 {pct(med(exc))}　超额逐年为正 "
              f"{sum(1 for y in yrs if per_year[y][4] > 0)}/{len(yrs)} 年")

    # ---------------- 表 D：样本独立性
    print("\n表 D　样本独立性（`换仓·减一档` 每天只卖一档，同一配对会连周重复）")
    print(f"  {'年':<6}{'换仓笔数':>9}{'不同配对':>9}{'不同源':>8}{'不同标的':>9}")
    for y in sorted({d[:4] for d, _, _ in swaps}):
        g = [(d, s, t) for d, s, t in swaps if d[:4] == y]
        print(f"  {y:<6}{len(g):>9}{len({(s, t) for _, s, t in g}):>9}"
              f"{len({s for _, s, _ in g}):>8}{len({t for _, _, t in g}):>9}")
    for label, lo, hi in epoch_rows({d[:4]: 1 for d, _, _ in swaps}, a.split):
        g = [(d, s, t) for d, s, t in swaps if lo <= d[:4] <= hi]
        if g:
            print(f"  {label} {lo}-{hi}　{len(g)} 笔 / {len({(s, t) for _, s, t in g})} 个不同配对"
                  f" / {len({s for _, s, _ in g})} 源 / {len({t for _, _, t in g})} 标的")

    print("\n口径提示：表 C 的买腿与卖腿超额对匹配容差敏感，报结论时同报 `--tol` 的取值范围；"
          "\n表 D 的配对数才是表 3「日数」的有效上界。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

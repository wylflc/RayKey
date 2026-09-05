#!/usr/bin/env python3
"""「买在盈利顶」审计（OI-115 第二问，用户 2026-09-01 指令）。

OI-115 登记的顺周期只是**统计性质**；能决定要不要动 §6.5.1 的，是它有没有真的把钱投出去：
`V` 在周期高点被抬高 → `P/V` 跌破买入线 → 该票进了前几名 → 真的成交。本脚本量的就是这一条链。

三张表：

* **表 1 盈利分位 × 买入金额**——把每一笔 `买入` 按当时 TTM 归母净利相对**自身十年中位**的倍数
  `s = TTM / 十年中位` 分档（档界 0.8／1.3／1.6 对齐 §6.5.1 峰守卫坡道的 `K−ramp`／`K`），
  报笔数、金额占比、买入时 `P/V`、其后 2 年利润最低点相对买入时的倍数、前向 250／500 日总回报。
  **`s ≥ 1.3` 且其后利润腰斩的那一格，就是「买在盈利顶」。**
* **表 2 点名核对**——给定代码在给定窗口内的逐月 `P/V` 最低值、是否跌破买入线、是否真的成交。
  用来回答「2021 白酒高峰会不会触发买白酒」这类问题，包括从未被买过的票。
* **表 3 命中清单**——`s ≥ 1.3` 的买入按金额降序逐笔列出。

利润峰的判定是**回望的**（要知道其后崩没崩），故本表是诊断，不是可交易信号，也不进 §12.1 的决策读数。

用法：
    python3 scripts/experimental/cycle_peak_buy_audit.py \\
        --trade-log data/experiments/exp_oi114_adopt_m19/trades_ledger_m19.csv \\
        --states data/processed/a_share_daily_states_adopted.csv \\
        --bands data/processed/roic_bands.csv \\
        --buy-line 0.9343 \\
        --name-check 白酒=600519,000858,000568,002304,600809@2019-01:2022-12
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

BUCKETS = ((0.0, 0.8, "≤0.80  低谷"), (0.8, 1.3, "0.80~1.30  常态"),
           (1.3, 1.6, "1.30~1.60  坡道内"), (1.6, 9e9, "≥1.60  峰守卫区"))


def ttm_series(series: dict[str, dict]) -> dict[str, float]:
    """{报告期: TTM 归母净利}。年报行取年报值；季报行 = 上年年报 + 本期 YTD − 上年同期 YTD。"""
    out: dict[str, float] = {}
    for period, row in series.items():
        ytd = bhv._num(row.get("parent_netprofit"))
        if ytd is None:
            continue
        if period.endswith("-12-31"):
            out[period] = ytd
            continue
        year = int(period[:4])
        annual = series.get(f"{year - 1}-12-31")
        prev = series.get(f"{year - 1}{period[4:]}")
        a = bhv._num(annual.get("parent_netprofit")) if annual else None
        p = bhv._num(prev.get("parent_netprofit")) if prev else None
        if a is None or p is None:
            continue
        out[period] = a + ytd - p
    return out


def peak_ratio(ttm: dict[str, float], period: str, years: int = 10) -> float | None:
    """`TTM(period) ÷ 该期之前 years 年 TTM 的中位`；中位 ≤ 0 或样本不足 6 期返回 None。"""
    now = ttm.get(period)
    if now is None:
        return None
    lo = f"{int(period[:4]) - years}{period[4:]}"
    hist = [v for p, v in ttm.items() if lo <= p < period]
    if len(hist) < 6:
        return None
    med = statistics.median(hist)
    if med <= 0:
        return None
    return now / med


def forward_trough(ttm: dict[str, float], period: str, years: int = 2) -> float | None:
    """其后 years 年内 TTM 的最低点 ÷ 本期 TTM；本期 ≤ 0 或无后续报告返回 None。"""
    now = ttm.get(period)
    if now is None or now <= 0:
        return None
    hi = f"{int(period[:4]) + years}{period[4:]}"
    fwd = [v for p, v in ttm.items() if period < p <= hi]
    return min(fwd) / now if fwd else None


def load_band_rows(path: Path, codes: set[str]) -> dict[tuple[str, str], dict]:
    out = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            code = r["security_code"].zfill(6)
            if code in codes:
                out[(code, r["report_date"])] = r
    return out


def load_state_index(path: Path, codes: set[str]) -> tuple[dict, dict]:
    """(逐日 {(代码,日期): (P/V, band_report_date)}, 月末 {代码: {年月: (日期, P/V)}})，只取给定代码。"""
    daily: dict[tuple[str, str], tuple[float, str]] = {}
    month: dict[str, dict[str, tuple[str, float]]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        i_code, i_date, i_pv = (header.index("security_code"), header.index("date"),
                                header.index("valuation_ratio"))
        i_brd = header.index("band_report_date")
        for row in reader:
            code = row[i_code].zfill(6)
            if code not in codes or not row[i_pv]:
                continue
            pv = float(row[i_pv])
            daily[(code, row[i_date])] = (pv, row[i_brd])
            ym = row[i_date][:7]
            prev = month[code].get(ym)
            if prev is None or row[i_date] > prev[0]:
                month[code][ym] = (row[i_date], pv)
    return daily, dict(month)


def fwd_return(tr: dict[str, float], days: list[str], day: str, horizon: int) -> float | None:
    i = bisect.bisect_left(days, day)
    if i >= len(days):
        return None
    j = i + horizon
    if j >= len(days):
        return None
    a, b = tr.get(days[i]), tr.get(days[j])
    return (b / a - 1.0) if (a and b and a > 0) else None


def fmt_pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x * 100:+.{digits}f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade-log", type=Path, required=True)
    ap.add_argument("--states", type=Path, required=True, help="候选侧逐日状态（买入线判在这一侧）")
    ap.add_argument("--bands", type=Path, required=True)
    ap.add_argument("--buy-line", type=float, default=0.9343)
    ap.add_argument("--peak-years", type=int, default=10, help="盈利峰的回看年数，缺省 10（对齐峰守卫）")
    ap.add_argument("--trough-years", type=int, default=2, help="其后利润低点的观察年数，缺省 2")
    ap.add_argument("--name-check", action="append", default=[], metavar="名=代码,…@起:止",
                    help="点名核对一组代码在窗口内的最低 P/V 与成交，可重复；窗口写 YYYY-MM:YYYY-MM")
    args = ap.parse_args()

    buys = []
    with args.trade_log.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["action"] == "买入":
                buys.append((r["date"], r["security_code"].zfill(6), float(r["amount"]),
                             float(r["pv_ratio"]) if r["pv_ratio"] else None, r.get("reason", "")))
    named: list[tuple[str, list[str], str, str]] = []
    for spec in args.name_check:
        label, _, rest = spec.partition("=")
        codes_s, _, window = rest.partition("@")
        lo, _, hi = window.partition(":")
        named.append((label, [c.strip().zfill(6) for c in codes_s.split(",") if c.strip()], lo, hi))

    codes = {c for _d, c, _a, _p, _r in buys} | {c for _l, cs, _lo, _hi in named for c in cs}
    financials = bhv.load_financials(codes)
    actions = bhv.load_actions()
    bands = load_band_rows(args.bands, codes)
    daily, month = load_state_index(args.states, codes)

    ttms = {c: ttm_series(financials.get(c, {})) for c in codes}
    tr_map, day_map = {}, {}
    for code in codes:
        path = ROOT / f"data/raw/ohlcv/{code}.csv"
        if not path.exists():
            continue
        prices = []
        with path.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    prices.append((r["date"], float(r["close"])))
                except (KeyError, TypeError, ValueError):
                    pass
        prices.sort()
        tr_map[code] = total_return_index(prices, actions.get(code, []))
        day_map[code] = [d for d, _ in prices]

    print(f"「买在盈利顶」审计｜流水 {args.trade_log.name}｜买入 {len(buys):,} 笔"
          f"｜盈利峰回看 {args.peak_years} 年、其后观察 {args.trough_years} 年｜买入线 {args.buy_line:.4f}")
    print("  s = 买入时 TTM 归母净利 ÷ 自身十年 TTM 中位；档界 0.8/1.3/1.6 对齐 §6.5.1 峰守卫坡道\n")

    rows = []
    for day, code, amount, pv, reason in buys:
        st = daily.get((code, day))
        period = st[1] if st else None
        band = bands.get((code, period)) if period else None
        t = ttms.get(code, {})
        s = peak_ratio(t, period, args.peak_years) if period else None
        trough = forward_trough(t, period, args.trough_years) if period else None
        f250 = fwd_return(tr_map.get(code, {}), day_map.get(code, []), day, 250)
        f500 = fwd_return(tr_map.get(code, {}), day_map.get(code, []), day, 500)
        rows.append({"day": day, "code": code, "amount": amount, "pv": pv, "reason": reason,
                     "period": period, "s": s, "trough": trough, "f250": f250, "f500": f500,
                     "pw": float(band["peak_weight"]) if band and band.get("peak_weight") else None,
                     "trust": float(band["growth_trust"]) if band and band.get("growth_trust") else None,
                     "name": band.get("security_name", "") if band else ""})

    total_amt = sum(r["amount"] for r in rows)
    unknown = [r for r in rows if r["s"] is None]
    print(f"  表 1　盈利分位 × 买入金额（可判 s 的 {len(rows) - len(unknown):,} 笔／"
          f"{(total_amt - sum(r['amount'] for r in unknown)) / 1e4:,.0f} 万元；"
          f"不可判 {len(unknown):,} 笔／{sum(r['amount'] for r in unknown) / 1e4:,.0f} 万元）")
    print(f"  {'盈利分位 s':<20}{'笔数':>6}{'金额占比':>9}{'买入P/V中位':>12}"
          f"{'其后2年利润低点':>15}{'腰斩占比':>9}{'前向250日':>11}{'前向500日':>11}")
    for lo, hi, label in BUCKETS:
        grp = [r for r in rows if r["s"] is not None and lo <= r["s"] < hi]
        if not grp:
            print(f"  {label:<20}{0:>6}")
            continue
        amt = sum(r["amount"] for r in grp)
        tro = [r["trough"] for r in grp if r["trough"] is not None]
        f250 = [r["f250"] for r in grp if r["f250"] is not None]
        f500 = [r["f500"] for r in grp if r["f500"] is not None]
        halved = sum(1 for v in tro if v < 0.5) / len(tro) if tro else None
        print(f"  {label:<20}{len(grp):>6}{amt / total_amt * 100:>8.1f}%"
              f"{statistics.median([r['pv'] for r in grp if r['pv'] is not None]):>12.4f}"
              f"{(f'{statistics.median(tro):.2f}x' if tro else '—'):>15}"
              f"{(f'{halved * 100:.0f}%' if halved is not None else '—'):>9}"
              f"{fmt_pct(statistics.median(f250) if f250 else None):>11}"
              f"{fmt_pct(statistics.median(f500) if f500 else None):>11}")

    for label, codes_s, lo, hi in named:
        print(f"\n  表 2　点名核对：{label}（{lo}~{hi}）")
        print(f"  {'代码':<8}{'名称':<12}{'窗口最低P/V':>12}{'落在':>12}{'跌破买入线月数':>15}"
              f"{'窗口内买入':>11}{'买入金额(万)':>13}")
        for code in codes_s:
            months = {ym: v for ym, v in month.get(code, {}).items() if lo <= ym <= hi}
            if not months:
                print(f"  {code:<8}{'（窗口内无在册状态）':<12}")
                continue
            best_ym = min(months, key=lambda k: months[k][1])
            below = sum(1 for _d, v in months.values() if v <= args.buy_line)
            hit = [r for r in rows if r["code"] == code and lo <= r["day"][:7] <= hi]
            name = next((r["name"] for r in rows if r["code"] == code and r["name"]), "")
            if not name:
                nb = next((b for (c, _p), b in bands.items() if c == code), None)
                name = nb.get("security_name", "") if nb else ""

            print(f"  {code:<8}{name:<12}{months[best_ym][1]:>12.4f}{best_ym:>12}"
                  f"{f'{below}/{len(months)}':>15}{len(hit):>11}"
                  f"{sum(r['amount'] for r in hit) / 1e4:>13,.0f}")

    # 表 4：s 与「其后利润是否崩塌」的交叉表——**只有右上角那格才是「买在周期顶」**。
    # s 高本身不等于周期顶：一家持续增长的公司 TTM 永远高于自身十年中位，s 天然 >1.6。
    # 分辨两者的唯一办法是看其后利润有没有塌。
    print(f"\n  表 4　s × 其后 {args.trough_years} 年利润低点 的交叉表（笔数／金额占比／前向 500 日中位；"
          f"前向读数只统计有 500 日后续行情的买入）")
    # 下界取 −inf：利润转负时 trough 为负，落在 0 以下，不能被 0.0 挡在表外（那是最坏的一格）
    tro_buckets = ((-9e9, 0.5, "崩塌 <0.5x（含转负）"), (0.5, 0.8, "回落 0.5~0.8x"), (0.8, 9e9, "未落 ≥0.8x"))
    print(f"  {'盈利分位 s':<20}" + "".join(f"{lab:>26}" for _lo, _hi, lab in tro_buckets))
    for lo, hi, label in BUCKETS:
        cells = []
        for tlo, thi, _tlab in tro_buckets:
            grp = [r for r in rows if r["s"] is not None and lo <= r["s"] < hi
                   and r["trough"] is not None and tlo <= r["trough"] < thi]
            f500 = [r["f500"] for r in grp if r["f500"] is not None]
            amt = sum(r["amount"] for r in grp) / total_amt * 100
            cells.append(f"{len(grp):>5}笔 {amt:>5.1f}% "
                         f"{(fmt_pct(statistics.median(f500), 0) if f500 else '—'):>7}")
        print(f"  {label:<20}" + "".join(f"{c:>26}" for c in cells))
    peak_trap = [r for r in rows if r["s"] is not None and r["s"] >= 1.3
                 and r["trough"] is not None and r["trough"] < 0.5]
    pt500 = [r["f500"] for r in peak_trap if r["f500"] is not None]
    print(f"  「买在顶」（s ≥ 1.30 且其后 {args.trough_years} 年利润腰斩）："
          f"{len(peak_trap)} 笔／{sum(r['amount'] for r in peak_trap) / 1e4:,.0f} 万元／"
          f"占全部买入金额 {sum(r['amount'] for r in peak_trap) / total_amt * 100:.1f}%；"
          f"其中有 500 日后续的 {len(pt500)} 笔前向中位 "
          f"{fmt_pct(statistics.median(pt500)) if pt500 else '—'}")

    hits = sorted([r for r in rows if r["s"] is not None and r["s"] >= 1.3],
                  key=lambda r: -r["amount"])
    print(f"\n  表 3　命中清单：s ≥ 1.30 的买入 {len(hits)} 笔／"
          f"{sum(r['amount'] for r in hits) / 1e4:,.0f} 万元（占全部买入金额 "
          f"{sum(r['amount'] for r in hits) / total_amt * 100:.1f}%），按金额降序前 30 笔")
    print(f"  {'日期':<12}{'代码':<8}{'名称':<11}{'金额(万)':>10}{'P/V':>8}{'s':>7}"
          f"{'峰权w':>7}{'λ':>6}{'后2年低点':>10}{'前向250':>10}{'前向500':>10}")
    for r in hits[:30]:
        pw = f"{r['pw']:.2f}" if r["pw"] is not None else "—"
        tw = f"{r['trust']:.1f}" if r["trust"] is not None else "—"
        tro = f"{r['trough']:.2f}x" if r["trough"] is not None else "—"
        print(f"  {r['day']:<12}{r['code']:<8}{r['name']:<11}{r['amount'] / 1e4:>10,.0f}"
              f"{(r['pv'] if r['pv'] is not None else 0):>8.3f}{r['s']:>7.2f}"
              f"{pw:>7}{tw:>6}{tro:>10}"
              f"{fmt_pct(r['f250'], 0):>10}{fmt_pct(r['f500'], 0):>10}")


if __name__ == "__main__":
    main()

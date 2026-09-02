#!/usr/bin/env python3
"""谷底对称守卫 × 走势闸门：估值侧放进来的「谷年公司」，操作侧的 `收 > MA20 > MA60` 能不能把不复苏的那批挡在门外？

信号层：在 v6b 宇宙、`P/V ≤ 买入线` 的逐日观测上，按「所用带是否被谷守卫触发（trough_weight > 0）」分两组，
再按当日是否过新建仓走势闸门分两层，比较其后 H 年送转折算收益（不含分红，与 §12.67 同口径）与
「该带年份的利润率是否在 H 年内脱离谷区」（`guard_reversion_check.judge`）。
以 (代码, 带报告期) 为一个**episode**：首个在线内日 = 估值侧放行日；首个「在线内且过闸门」日 = 策略真正可买日。
路径层（可选 `--ledger`）：把某次长跑的买入流水按买入日所用带是否被谷守卫触发分组，列出笔数、金额与代码。

用法：
  trough_gate_trend_check.py --states data/processed/a_share_daily_states_adopted.csv --bands data/processed/roic_bands.csv \
      --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --buy-line 1.0454 [--horizon 3] [--ledger <ledger.csv>]
"""
import argparse
import bisect
import collections
import csv
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import backtest_valuation_strategy as bvs  # noqa: E402
import build_historical_valuation_bands as bhv  # noqa: E402
from guard_reversion_check import judge, load as load_bands  # noqa: E402
from valuation_forward_check import active, load_spans  # noqa: E402


def add_years(day: str, years: int) -> str:
    y, m, d = map(int, day.split("-"))
    try:
        return date(y + years, m, d).isoformat()
    except ValueError:
        return date(y + years, m, 28).isoformat()


def fwd_return(prices: dict, days: dict, bactions: dict, code: str, day: str, years: int):
    """其后 `years` 年的送转折算收益（只计送转、不含分红，与 `valuation_forward_check.py` 同口径）；
    目标日须有 62 天内的收盘，长期停牌不算。"""
    series, ds = prices.get(code), days.get(code)
    if not series or day not in series:
        return None
    target = add_years(day, years)
    j = bisect.bisect_right(ds, target) - 1
    if j < 0 or (date.fromisoformat(target) - date.fromisoformat(ds[j])).days > 62:
        return None
    factor = bhv.split_factor(bactions.get(code, []), day, ds[j])
    r = series[ds[j]] * factor / series[day] - 1.0
    return None if r <= -1 else r


def fmt(vals):
    if not vals:
        return "—"
    return f"中位 {statistics.median(vals)*100:+.1f}%／均值 {statistics.fmean(vals)*100:+.1f}%（n={len(vals)}）"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", type=Path, required=True)
    ap.add_argument("--bands", type=Path, required=True)
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--buy-line", type=float, required=True)
    ap.add_argument("--since", default="2009-11-01")
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--max-rows", type=int, default=0, help="只读前 N 行（自测用）")
    args = ap.parse_args()
    H = args.horizon

    spans = load_spans(args.panel)
    codes = set(spans)
    annual, names, trig, _ = load_bands(args.bands)
    guard = {}                                  # (code, report_date) -> (trough_w, peak_w)
    with args.bands.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["security_code"] in codes:
                tw = float(r["trough_weight"] or 0) if r.get("trough_weight") else 0.0
                pw = float(r["peak_weight"] or 0) if r.get("peak_weight") else 0.0
                guard[(r["security_code"], r["report_date"])] = (tw, pw)
    print(f"宇宙 {len(codes)} 只；带 {len(guard)} 条，其中谷守卫触发 {sum(1 for v in guard.values() if v[0] > 0)}", file=sys.stderr)

    prices = bvs._load_ohlcv_column("close", codes)
    actions = bvs.load_actions()
    mas = {c: bvs.adjusted_moving_averages(s, actions.get(c, {}), (20, 60)) for c, s in prices.items()}
    bactions = bhv.load_actions()
    days = {c: sorted(s) for c, s in prices.items()}
    print("行情与均线就绪", file=sys.stderr)

    ledger_buys = collections.defaultdict(list)   # (code, date) -> [(amount, name)]
    if args.ledger:
        with args.ledger.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["action"] == "买入":
                    ledger_buys[(r["security_code"], r["date"])].append(float(r["amount"]))

    ep = {}                                      # (code, report_date) -> dict
    rows = collections.Counter()                 # (guarded, passed) -> row-days
    row_fwd = collections.defaultdict(list)      # (guarded, passed) -> fwd returns（逐日观测）
    ledger_hit = {}                              # (code, date) -> guarded?
    with args.states.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        ic, idt, icl, ibr, ipv = (header.index(k) for k in ("security_code", "date", "close", "band_report_date", "valuation_ratio"))
        for n, r in enumerate(reader, 1):
            if args.max_rows and n > args.max_rows:
                break
            code = r[ic]
            if code not in codes:
                continue
            day = r[idt]
            if day < args.since or not active(spans[code], day):
                continue
            key = (code, r[ibr])
            g = guard.get(key)
            if (code, day) in ledger_buys:
                ledger_hit[(code, day)] = bool(g and g[0] > 0)
            try:
                pv = float(r[ipv])
                close = float(r[icl])
            except ValueError:
                continue
            if pv > args.buy_line or g is None:
                continue
            guarded = g[0] > 0
            ma = mas.get(code, {}).get(day)
            passed = bool(ma and 20 in ma and 60 in ma and close > ma[20] > ma[60])
            rows[(guarded, passed)] += 1
            fr = fwd_return(prices, days, bactions, code, day, H)
            if fr is not None:
                row_fwd[(guarded, passed)].append(fr)
            e = ep.setdefault(key, {"guarded": guarded, "first": day, "first_pass": None, "n": 0, "n_pass": 0})
            e["n"] += 1
            if passed:
                e["n_pass"] += 1
                if e["first_pass"] is None:
                    e["first_pass"] = day
    print(f"在线内逐日观测 {sum(rows.values())}，episode {len(ep)}", file=sys.stderr)

    print(f"# 谷底对称守卫 × 走势闸门（宇宙 v6b，买入线 {args.buy_line}，{args.since} 起，前向 {H} 年，只计送转不含分红）\n")
    print("## 逐日观测（在线内行 × 是否过 `收 > MA20 > MA60`）\n")
    print("| 带被谷守卫触发 | 过闸门 | 行数 | 其后收益 |")
    print("| --- | --- | ---: | --- |")
    for guarded in (True, False):
        for passed in (True, False):
            print(f"| {'是' if guarded else '否'} | {'是' if passed else '否'} | {rows[(guarded, passed)]} | {fmt(row_fwd[(guarded, passed)])} |")

    print(f"\n## episode（(代码, 带报告期)；首个在线内日 = 估值侧放行日，首个在线内且过闸门日 = 策略可买日）\n")
    print("| 带被谷守卫触发 | episode 数 | 有可买日的占比 | 从放行日起其后收益（全部） | 从可买日起其后收益（有可买日者） | 从放行日起其后收益（无可买日者） | 利润率 H 年内脱离谷区：有可买日 vs 无可买日 |")
    print("| --- | ---: | ---: | --- | --- | --- | --- |")
    for guarded in (True, False):
        eps = [e for e in ep.values() if e["guarded"] == guarded]
        with_pass = [e for e in eps if e["first_pass"]]
        no_pass = [e for e in eps if not e["first_pass"]]
        def fr_of(es, key):
            out = []
            for (code, rd), e in ep.items():
                if e in es:
                    d = e[key]
                    if d:
                        v = fwd_return(prices, days, bactions, code, d, H)
                        if v is not None:
                            out.append(v)
            return out
        def esc_of(es):
            hit = tot = 0
            for (code, rd), e in ep.items():
                if e in es:
                    res = judge(annual[code], int(rd[:4]), "trough", H)
                    if res is not None:
                        tot += 1
                        hit += res[3]
            return f"{hit}/{tot}（{hit/tot*100:.0f}%）" if tot else "—"
        esc_txt = f"{esc_of(with_pass)} vs {esc_of(no_pass)}" if guarded else f"{esc_of(with_pass)} vs {esc_of(no_pass)}（非触发带，脱离判据不适用，只列参考）"
        print(f"| {'是' if guarded else '否'} | {len(eps)} | {len(with_pass)/len(eps)*100 if eps else 0:.0f}% | {fmt(fr_of(eps, 'first'))} | {fmt(fr_of(with_pass, 'first_pass'))} | {fmt(fr_of(no_pass, 'first'))} | {esc_txt} |")

    # 谷守卫 episode 逐票：哪些公司被放进买入线、闸门放没放、结局如何
    print("\n## 谷守卫触发的 episode 逐票（按 episode 数排序，前 30）\n")
    print("| 代码 | 名称 | episode | 有可买日 | 可买日起其后收益中位 | 利润率脱离谷区 |")
    print("| --- | --- | ---: | ---: | ---: | --- |")
    per = collections.defaultdict(list)
    for (code, rd), e in ep.items():
        if e["guarded"]:
            per[code].append((rd, e))
    for code, lst in sorted(per.items(), key=lambda kv: -len(kv[1]))[:30]:
        wp = [e for _, e in lst if e["first_pass"]]
        frs = [fwd_return(prices, days, bactions, code, e["first_pass"], H) for e in wp]
        frs = [v for v in frs if v is not None]
        esc = [judge(annual[code], int(rd[:4]), "trough", H) for rd, _ in lst]
        esc = [r[3] for r in esc if r is not None]
        print(f"| {code} | {names.get(code, '')} | {len(lst)} | {len(wp)} | {statistics.median(frs)*100:+.1f}% | {sum(esc)}/{len(esc)} |" if frs else
              f"| {code} | {names.get(code, '')} | {len(lst)} | {len(wp)} | — | {sum(esc)}/{len(esc)} |")

    if args.ledger:
        print(f"\n## 路径层：{args.ledger} 的买入流水按所用带是否被谷守卫触发分组\n")
        g_amt = collections.defaultdict(float); g_n = collections.Counter(); by_code = collections.defaultdict(float)
        for (code, day), amts in ledger_buys.items():
            hit = ledger_hit.get((code, day))
            if hit is None:
                continue
            g_n[hit] += len(amts); g_amt[hit] += sum(amts)
            if hit:
                by_code[code] += sum(amts)
        tot_n = g_n[True] + g_n[False]; tot_amt = g_amt[True] + g_amt[False]
        print(f"买入 {tot_n} 笔／{tot_amt/1e8:.2f} 亿，其中所用带被谷守卫触发的 **{g_n[True]} 笔／{g_amt[True]/1e8:.2f} 亿（{g_amt[True]/tot_amt*100 if tot_amt else 0:.1f}%）**")
        print("\n| 代码 | 名称 | 谷守卫带上的买入金额（亿） | 该公司谷年利润率 H 年内脱离谷区 |")
        print("| --- | --- | ---: | --- |")
        for code, amt in sorted(by_code.items(), key=lambda kv: -kv[1])[:15]:
            esc = [judge(annual[code], y, "trough", H) for c, y, s, w, cyc in trig if c == code and s == "trough"]
            esc = [r[3] for r in esc if r is not None]
            print(f"| {code} | {names.get(code, '')} | {amt/1e8:.2f} | {sum(esc)}/{len(esc)} |")


if __name__ == "__main__":
    main()

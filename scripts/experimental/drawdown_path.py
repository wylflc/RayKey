"""回撤路径剖析：最大的几次回撤各自是怎么跌下来的（研究工具，不进生产流程）。

输入：一次带产物的回测（*_equity.csv、*_trades.csv、成交流水 tradelog）。
输出：前 N 次回撤的峰谷日期、深度、杠杆、指数对照、期内买卖流水、
     以及「峰值时已持仓（老仓）」与「峰值后新建/加仓（新钱）」两层的盈亏归因。

用法：python3 scripts/experimental/drawdown_path.py <回测产物目录> [--top 3]
（目录里须有一次带产物的回测：*_equity.csv、*_trades.csv 与 --trade-log 写出的 tradelog*.csv）
首用于回测日志 §12.92（2026-08-20）：三段最大回撤的老仓/新钱两层拆解。
"""
import argparse
import bisect
import collections
import csv
import os
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OHLCV = ROOT / "data/raw/ohlcv"
ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
NAMES = ROOT / "data/raw/a_share_securities.csv"


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_index(name):
    p = OHLCV / f"INDEX_{name}.csv"
    out = {}
    with p.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            c = fnum(r.get("close"))
            if c:
                out[r["date"]] = c
    return out


def load_close(code):
    p = OHLCV / f"{code}.csv"
    out = {}
    if not p.exists():
        return out
    with p.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            c = fnum(r.get("close"))
            if c and c > 0:
                out[r["date"]] = c
    return out


def load_actions():
    out = collections.defaultdict(dict)
    if not ACTIONS.exists():
        return out
    with ACTIONS.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            d = (r.get("ex_dividend_date") or "").strip()
            if not d:
                continue
            cash = fnum(r.get("cash_per_share")) or 0.0
            ratio = fnum(r.get("share_ratio")) or 0.0
            oc, orr = out[r["security_code"]].get(d, (0.0, 0.0))
            out[r["security_code"]][d] = (oc + cash, (1 + orr) * (1 + ratio) - 1)
    return out


def load_names():
    out = {}
    if not NAMES.exists():
        return out
    with NAMES.open(newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        cols = rd.fieldnames or []
        ccol = next((c for c in cols if "code" in c.lower()), None)
        ncol = next((c for c in cols if "name" in c.lower()), None)
        if not ccol or not ncol:
            return out
        for r in rd:
            out[r[ccol]] = r[ncol]
    return out


def episodes(curve):
    """所有回撤段：(峰日, 峰值, 谷日, 谷值, 深度, 恢复日或None)。"""
    out = []
    peak_day, peak = curve[0][0], curve[0][1]
    trough_day, trough = None, peak
    in_dd = False
    for day, eq in curve:
        if eq >= peak:
            if in_dd:
                out.append((peak_day, peak, trough_day, trough, 1 - trough / peak, day))
                in_dd = False
            peak_day, peak = day, eq
            trough_day, trough = day, eq
        else:
            if not in_dd:
                in_dd = True
                trough_day, trough = day, eq
            elif eq < trough:
                trough_day, trough = day, eq
    if in_dd:
        out.append((peak_day, peak, trough_day, trough, 1 - trough / peak, None))
    return out


def ma_at(closes_sorted_days, closes, day, n=60):
    """简单均线：该股有行情的最近 n 个交易日收盘均值（含 day）。"""
    i = bisect.bisect_right(closes_sorted_days, day)
    if i < n:
        return None
    seg = closes_sorted_days[i - n:i]
    return sum(closes[d] for d in seg) / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_dir")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--min-depth", type=float, default=0.0)
    ap.add_argument("--path-step", type=int, default=10, help="路径表抽样间隔（交易日）")
    ap.add_argument("--stocks", type=int, default=25, help="每段最多列多少只老仓")
    args = ap.parse_args()
    d = Path(args.artifact_dir)
    eq_file = next(d.glob("*_equity.csv"))
    tr_file = next(d.glob("*_trades.csv"))
    log_file = next(d.glob("tradelog*.csv"))

    # ---- 净值曲线
    curve = []
    meta = {}
    with eq_file.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            curve.append((r["date"], float(r["net_equity"])))
            meta[r["date"]] = r
    days = [c[0] for c in curve]
    eqs = {c[0]: c[1] for c in curve}
    eps = sorted(episodes(curve), key=lambda e: -e[4])
    idx300 = load_index("000300")
    idx001 = load_index("000001")
    names = load_names()
    actions = load_actions()

    # ---- 逐笔流水 / 逐周期
    ledger = []
    with log_file.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ledger.append(r)
    cycles = []
    with tr_file.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cycles.append(r)
    cyc_by_code = collections.defaultdict(list)
    for c in cycles:
        cyc_by_code[c["security_code"]].append(c)

    def cycle_of(code, day):
        for c in cyc_by_code.get(code, []):
            if c["entry_date"] <= day and (not c["exit_date"] or day <= c["exit_date"]):
                return c
        return None

    def classify(reason):
        if "止损" in reason or "强制平仓" in reason:
            return "止损"
        if "换仓" in reason or "升级" in reason or "相关性冲突" in reason:
            return "换仓"
        if "移出" in reason:
            return "出名单"
        if "P/V" in reason or "分位" in reason:
            return "减持"
        if "清仓保护" in reason or "围栏" in reason or "大盘" in reason:
            return "围栏"
        if "截止清算" in reason:
            return "清算"
        return "其它"

    # ---- 用流水重建逐日股数（含送转），用于归因
    ledger_by_day = collections.defaultdict(list)
    for r in ledger:
        ledger_by_day[r["date"]].append(r)
    all_codes = sorted({r["security_code"] for r in ledger})
    closes = {c: load_close(c) for c in all_codes}
    cdays = {c: sorted(v) for c, v in closes.items()}

    # 逐日持仓 shares[code]、均价 cost[code]（按买入均价，送转同比例调）
    shares = collections.defaultdict(float)
    cost = collections.defaultdict(float)       # 累计买入金额（本周期）
    bought = collections.defaultdict(float)     # 累计买入股数（本周期，送转同调）
    hold_by_day = {}                            # day -> {code: (shares, avgcost)}
    last_px = {}
    for day in days:
        for code in list(shares):
            ev = actions.get(code, {}).get(day)
            if ev and shares[code] > 0:
                ratio = ev[1]
                if ratio:
                    shares[code] *= (1 + ratio)
                    bought[code] *= (1 + ratio)
        for r in ledger_by_day.get(day, []):
            code, n, px = r["security_code"], float(r["shares"]), float(r["price"])
            if r["action"] == "买入":
                if shares[code] <= 0:          # 新周期
                    cost[code] = 0.0
                    bought[code] = 0.0
                shares[code] += n
                cost[code] += n * px
                bought[code] += n
            else:
                shares[code] -= n
                if shares[code] < 1e-6:
                    shares[code] = 0.0
        snap = {}
        for code, n in shares.items():
            if n > 0:
                px = closes[code].get(day)
                if px:
                    last_px[code] = px
                snap[code] = (n, cost[code] / bought[code] if bought[code] else 0.0,
                              last_px.get(code))
        hold_by_day[day] = snap

    # 重建校验：Σ股数×价 vs 净值−现金+负债
    def holdings_value(day):
        return sum(n * px for n, _c, px in hold_by_day[day].values() if px)

    def actual_holdings(day):
        m = meta[day]
        return float(m["net_equity"]) - float(m["cash"]) + float(m["debt"] or 0)

    print(f"# 回撤路径剖析：{eq_file.name}")
    print(f"区间 {days[0]} ~ {days[-1]}，{len(days)} 个交易日；期末净值 {curve[-1][1]/1e4:,.0f} 万")
    print(f"\n## 全部回撤段（按深度排序，前 12 段）")
    print(f"{'#':>2} {'峰日':>10} {'谷日':>10} {'恢复日':>10} {'深度':>7} {'跌程日':>6} {'恢复日数':>7} "
          f"{'峰净值万':>9} {'峰杠杆':>7} {'峰仓位':>7} {'沪深300同窗':>10}")
    for i, (pd_, pk, td, tv, depth, rd) in enumerate(eps[:12], 1):
        i_pd = days.index(pd_)
        i_td = days.index(td)
        rec = days.index(rd) - i_td if rd else None
        m = meta[pd_]
        debt = float(m["debt"] or 0)
        lev = (pk + debt) / pk if pk else 0
        pos_w = 1 - float(m["cash_ratio"] or 0) + debt / pk if pk else 0
        b0, b1 = idx300.get(pd_), idx300.get(td)
        bret = (b1 / b0 - 1) if b0 and b1 else float("nan")
        print(f"{i:>2} {pd_:>10} {td:>10} {rd or '未恢复':>10} {depth:>7.1%} {i_td-i_pd:>6} "
              f"{rec if rec is not None else '—':>7} {pk/1e4:>9,.0f} {lev:>7.2f} {pos_w:>7.0%} {bret:>10.1%}")

    for rank, (pd_, pk, td, tv, depth, rd) in enumerate(eps[:args.top], 1):
        if depth < args.min_depth:
            break
        i_pd, i_td = days.index(pd_), days.index(td)
        i_rd = days.index(rd) if rd else len(days) - 1
        win = days[i_pd:i_td + 1]
        print(f"\n\n## 第 {rank} 大回撤：{pd_} → {td}（−{depth:.1%}），"
              f"{'恢复于 ' + rd if rd else '至今未恢复'}")
        mp, mt = meta[pd_], meta[td]
        for tag, m, day in (("峰值日", mp, pd_), ("谷底日", mt, td)):
            eq = float(m["net_equity"]); debt = float(m["debt"] or 0); cash = float(m["cash"])
            gross = eq + debt
            print(f"- {tag} {day}：净值 {eq/1e4:,.0f} 万｜持仓市值 {(gross-cash)/1e4:,.0f} 万"
                  f"（占净值 {(gross-cash)/eq:.0%}）｜现金 {cash/1e4:,.0f} 万｜融资 {debt/1e4:,.0f} 万"
                  f"｜担保比例 {m['margin_ratio'] or '无负债'}｜持仓 {m['positions']} 只"
                  f"｜前1/前3权重 {float(m['top1_weight']):.0%}/{float(m['top3_weight']):.0%}")
        # 重建校验
        for day in (pd_, td):
            rv, av = holdings_value(day), actual_holdings(day)
            print(f"  重建校验 {day}：流水重建持仓市值 {rv/1e4:,.0f} 万 vs 净值表推算 {av/1e4:,.0f} 万"
                  f"（误差 {rv/av-1:+.1%}）" if av else "")
        # 指数对照
        for iname, idx in (("沪深300", idx300), ("上证", idx001)):
            seq = [(dd, idx[dd]) for dd in win if dd in idx]
            if len(seq) < 2:
                continue
            lv0, lv1 = seq[0][1], seq[-1][1]
            # 指数自身在窗口内的最大回撤 & 指数相对其历史前高的位置
            prior = [v for dd, v in idx.items() if dd <= pd_]
            hist_peak = max(prior) if prior else lv0
            pk_, worst = -1, 0
            for _d, v in seq:
                pk_ = max(pk_, v); worst = max(worst, 1 - v / pk_)
            # 期内最差 5/10/20 日
            vals = [v for _d, v in seq]
            def worst_n(n):
                return min((vals[i] / vals[i - n] - 1 for i in range(n, len(vals))), default=float("nan"))
            big3 = sum(1 for i in range(1, len(vals)) if vals[i] / vals[i-1] - 1 <= -0.03)
            big5 = sum(1 for i in range(1, len(vals)) if vals[i] / vals[i-1] - 1 <= -0.05)
            print(f"- {iname}：峰日 {lv0:,.0f} → 谷日 {lv1:,.0f}（{lv1/lv0-1:+.1%}）；"
                  f"峰日时距其历史前高 {lv0/hist_peak-1:+.1%}；同窗自身最大回撤 {worst:.1%}；"
                  f"期内最差5/10/20日 {worst_n(5):+.1%}/{worst_n(10):+.1%}/{worst_n(20):+.1%}；"
                  f"单日≤−3% {big3} 次、≤−5% {big5} 次")

        # 路径表
        print(f"\n### 路径（每 {args.path_step} 个交易日抽样）")
        print(f"{'日期':>10} {'净值万':>8} {'回撤':>7} {'仓位':>5} {'现金%':>5} {'融资万':>7} {'担保':>5} "
              f"{'只数':>4} {'沪深300':>8} {'300回撤':>7}")
        b0 = idx300.get(pd_)
        bpk = b0 or 0
        for j in range(i_pd, i_td + 1):
            day = days[j]
            bv = idx300.get(day)
            if bv:
                bpk = max(bpk, bv)
            if (j - i_pd) % args.path_step and j != i_td:
                continue
            m = meta[day]; eq = float(m["net_equity"]); debt = float(m["debt"] or 0); cash = float(m["cash"])
            print(f"{day:>10} {eq/1e4:>8,.0f} {1-eq/pk:>7.1%} {(eq+debt-cash)/eq:>5.0%} {cash/eq:>5.0%} "
                  f"{debt/1e4:>7,.0f} {m['margin_ratio'] or '—':>5} {m['positions']:>4} "
                  f"{bv if bv else float('nan'):>8,.0f} {(1-bv/bpk) if bv else float('nan'):>7.1%}")

        # 期内买卖流水
        print(f"\n### 峰→谷期内成交流水")
        flow = collections.defaultdict(lambda: [0, 0.0])
        for r in ledger:
            if pd_ < r["date"] <= td:
                key = (r["action"], r["reason"] if r["action"] == "买入" else classify(r["reason"]))
                flow[key][0] += 1
                flow[key][1] += float(r["amount"])
        for (act, k), (n, amt) in sorted(flow.items(), key=lambda kv: -kv[1][1]):
            print(f"- {act}·{k}：{n} 笔，{amt/1e4:,.0f} 万")
        # 谷→恢复期
        if rd:
            flow2 = collections.defaultdict(lambda: [0, 0.0])
            for r in ledger:
                if td < r["date"] <= rd:
                    key = (r["action"], r["reason"] if r["action"] == "买入" else classify(r["reason"]))
                    flow2[key][0] += 1
                    flow2[key][1] += float(r["amount"])
            print(f"（谷→恢复 {td}→{rd}：" + "；".join(f"{a}·{k} {n}笔 {amt/1e4:,.0f}万"
                  for (a, k), (n, amt) in sorted(flow2.items(), key=lambda kv: -kv[1][1])) + "）")

        # ---- 两层归因：老仓（峰值日持有）vs 新钱（峰值后买入）
        snap_p = hold_by_day[pd_]
        # 显式跟踪两层股数：leg = 峰值日持有的股数（送转同调），new = 峰值后买入的股数。
        # 卖出先削新层（LIFO），卖出当日的成交盈亏按实际削掉的层归属；盯市盈亏按层内股数归属。
        leg = collections.defaultdict(float)
        new = collections.defaultdict(float)
        for c, (n, _a, _p) in snap_p.items():
            leg[c] = n
        px_last = {c: p for c, (_n, _a, p) in snap_p.items() if p}
        pnl_legacy = collections.defaultdict(float)
        pnl_new = collections.defaultdict(float)
        for j in range(i_pd + 1, i_td + 1):
            day = days[j]
            codes_today = set(c for c in leg if leg[c] > 0) | set(c for c in new if new[c] > 0) \
                | {r["security_code"] for r in ledger_by_day.get(day, [])}
            for code in codes_today:
                p0 = px_last.get(code)
                p1 = closes[code].get(day) or p0
                if p1 is None:
                    continue
                ev = actions.get(code, {}).get(day)
                adj = (1 + ev[1]) if ev else 1.0
                cash_ps = ev[0] if ev else 0.0
                # 盯市：昨日股数 × (今价×adj − 昨价) + 每股现金分红（分红进现金，净值不变，价却掉了）
                if p0 is not None:
                    pnl_legacy[code] += leg[code] * (p1 * adj - p0 + cash_ps)
                    pnl_new[code] += new[code] * (p1 * adj - p0 + cash_ps)
                leg[code] *= adj
                new[code] *= adj
                # 当日成交
                for r in ledger_by_day.get(day, []):
                    if r["security_code"] != code:
                        continue
                    n, px = float(r["shares"]), float(r["price"])
                    if r["action"] == "买入":
                        new[code] += n
                        pnl_new[code] += (p1 - px) * n
                    else:
                        k = min(n, new[code])
                        new[code] -= k
                        pnl_new[code] += (px - p1) * k
                        rest = n - k
                        if rest > 0:
                            leg[code] = max(0.0, leg[code] - rest)
                            pnl_legacy[code] += (px - p1) * rest
                px_last[code] = p1
        # 汇总
        d_eq = tv - pk
        s_leg = sum(pnl_legacy.values()); s_new = sum(pnl_new.values())
        resid = d_eq - s_leg - s_new
        print(f"\n### 两层归因（峰 {pd_} → 谷 {td}）")
        print(f"- 净值变化 {d_eq/1e4:+,.0f} 万 = 老仓层 {s_leg/1e4:+,.0f} 万（{s_leg/d_eq:.0%}）"
              f" + 新钱层 {s_new/1e4:+,.0f} 万（{s_new/d_eq:.0%}）"
              f" + 残差（费用/利息/分红/重建误差）{resid/1e4:+,.0f} 万")
        new_buy = sum(float(r["amount"]) for r in ledger
                      if pd_ < r["date"] <= td and r["action"] == "买入")
        new_first = sum(float(r["amount"]) for r in ledger
                        if pd_ < r["date"] <= td and r["action"] == "买入" and r["reason"] == "首次建仓")
        print(f"- 峰→谷期内投入新钱 {new_buy/1e4:,.0f} 万（其中新建仓 {new_first/1e4:,.0f} 万、"
              f"加仓（含对峰后新建仓位的加仓）{(new_buy-new_first)/1e4:,.0f} 万），占峰值净值 {new_buy/pk:.0%}；"
              f"新钱层亏损 {s_new/1e4:+,.0f} 万 = 投入的 {s_new/new_buy if new_buy else 0:+.0%}")
        # 老仓层明细
        print(f"\n### 峰值日老仓明细（按峰值市值降序，前 {args.stocks} 只）")
        print(f"{'代码':>6} {'名称':<8} {'峰值市值万':>9} {'权重':>5} {'浮盈%':>6} {'距止损%':>7} "
              f"{'止损价':>8} {'峰价':>8} {'期内老仓盈亏万':>10} {'离场日':>10} {'离场价':>8} {'离场原因':<16}")
        rows = []
        for code, (n, avgc, px) in snap_p.items():
            if not px:
                continue
            val = n * px
            cyc = cycle_of(code, pd_)
            stop = fnum(cyc["entry_stop"]) if cyc else None
            ma60 = ma_at(cdays[code], closes[code], pd_, 60)
            eff = min(stop, ma60) if stop and ma60 else (stop or ma60)
            dist = (px / eff - 1) if eff else float("nan")
            gain = (px / avgc - 1) if avgc else float("nan")
            # 离场：周期的 exit（若在窗口后仍持有则标注持有）
            exit_d = cyc["exit_date"] if cyc else ""
            exit_r = cyc["exit_reason"] if cyc else ""
            exit_px = None
            if exit_d:
                for r in ledger_by_day.get(exit_d, []):
                    if r["security_code"] == code and r["action"] == "卖出":
                        exit_px = float(r["price"])
                # 换算到峰值日的股本口径（峰→离场之间的送转连乘），便于与峰价直接比
                fac = 1.0
                for ex_d, (_c, ratio) in actions.get(code, {}).items():
                    if pd_ < ex_d <= exit_d and ratio:
                        fac *= (1 + ratio)
                if exit_px:
                    exit_px *= fac
            rows.append((val, code, n, avgc, px, gain, dist, eff, pnl_legacy.get(code, 0.0),
                         exit_d, exit_px, exit_r))
        rows.sort(key=lambda t: -t[0])
        for val, code, n, avgc, px, gain, dist, eff, pl, exit_d, exit_px, exit_r in rows[:args.stocks]:
            tag = exit_d if exit_d and exit_d <= td else (f"{exit_d}(谷后)" if exit_d else "持有至今")
            print(f"{code:>6} {names.get(code, '')[:8]:<8} {val/1e4:>9,.0f} {val/pk:>5.0%} {gain:>6.0%} "
                  f"{dist:>7.0%} {eff if eff else float('nan'):>8.2f} {px:>8.2f} {pl/1e4:>10,.0f} "
                  f"{tag:>10} {exit_px if exit_px else float('nan'):>8.2f} {classify(exit_r) + '·' + exit_r[:12]:<16}")
        # 老仓整体：峰值浮盈 vs 离场时
        tot_val = sum(r[0] for r in rows)
        tot_cost = sum(r[2] * r[3] for r in rows)
        print(f"- 老仓合计峰值市值 {tot_val/1e4:,.0f} 万，成本 {tot_cost/1e4:,.0f} 万，"
              f"峰值浮盈 {(tot_val-tot_cost)/1e4:+,.0f} 万（{tot_val/tot_cost-1:+.0%}）；"
              f"距生效止损线中位 {statistics.median([r[6] for r in rows if r[6] == r[6]]):+.0%}"
              f"（市值加权 {sum(r[6]*r[0] for r in rows if r[6]==r[6])/sum(r[0] for r in rows if r[6]==r[6]):+.0%}）")
        stopped_in = [r for r in rows if r[9] and r[9] <= td and classify(r[11]) == "止损"]
        print(f"- 老仓 {len(rows)} 只中，峰→谷期内被止损 {len(stopped_in)} 只"
              f"（峰值市值 {sum(r[0] for r in stopped_in)/1e4:,.0f} 万，占老仓 {sum(r[0] for r in stopped_in)/tot_val:.0%}），"
              f"止损时距峰日中位 {statistics.median([days.index(r[9]) - i_pd for r in stopped_in]) if stopped_in else '—'} 个交易日")
        # 新钱层：期内新建仓周期的结局
        new_cycles = [c for c in cycles if pd_ < c["entry_date"] <= td]
        if new_cycles:
            rets = [fnum(c["return_pct"]) for c in new_cycles if fnum(c["return_pct"]) is not None]
            inv = sum(float(c["invested"]) for c in new_cycles)
            pro = sum(float(c["proceeds"]) for c in new_cycles)
            closed_in = [c for c in new_cycles if c["exit_date"] and c["exit_date"] <= td]
            stopped = [c for c in closed_in if classify(c["exit_reason"]) == "止损"]
            hold = [int(c["holding_days"]) for c in closed_in if c["holding_days"]]
            print(f"- 峰→谷期内新建仓周期 {len(new_cycles)} 个：累计投入 {inv/1e4:,.0f} 万、回收 {pro/1e4:,.0f} 万"
                  f"（{pro/inv-1:+.1%}）；其中谷前已了结 {len(closed_in)} 个（止损 {len(stopped)} 个），"
                  f"了结周期持有天数中位 {statistics.median(hold) if hold else '—'} 天；"
                  f"周期收益中位 {statistics.median(rets):+.1%}" if rets else "")
            worst = sorted(new_cycles, key=lambda c: float(c["proceeds"]) - float(c["invested"]))[:8]
            print("  亏最多的新建仓：" + "；".join(
                f"{c['security_code']}{names.get(c['security_code'],'')[:4]} {c['entry_date']}→{c['exit_date'] or '持有'}"
                f" {(float(c['proceeds'])-float(c['invested']))/1e4:+,.0f}万({classify(c['exit_reason'])})" for c in worst))


if __name__ == "__main__":
    main()

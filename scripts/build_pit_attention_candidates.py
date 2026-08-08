#!/usr/bin/env python3
"""时点 worth_attention 重建的**候选粗筛**（OI-034 第 4 步，用户 2026-08-08 指令）。

它不是 §5
---------
§5.4.6 第 1 条写明「这是**模型逐家判断，不是阈值脚本**」。本脚本**不产出 worth_attention
名单**，只把某个历史时点上市的全部 A 股压缩成一份**可供逐家判断的候选表**，并打印
足够的事实（ROE 轨迹、毛利率、规模、增速）供判断时引用。判断本身由模型执行。

为什么需要它
------------
§12.9.10 已证明：把可选池从今日 261 只换成机械 ROE 筛选，年化 25.8% → 5.4%
（五起点差 19.0~22.6pp）。但那只证明了「单指标筛选不行」，**没有回答用户真正的问题**：
这 20pp 是 §5 选股能力挣的，还是今日名单的幸存者偏差？
要回答它，必须重建「**当年**按同一套 §5 标准会选出谁」——包括当年看着够格、
后来暴雷或平庸化因而**不在今天名单里**的那些公司。偏差就藏在这批公司里。

粗筛的定位与风险
----------------
粗筛是**召回工具**，不是标准。它只做一件事：把明显不可能通过资本复制测试的公司
（长期亏损、无毛利、微型规模）挡在逐家判断之外。**阈值刻意取整数、刻意宽松**——
若为了「更好地分开今日 261 与其他公司」去调阈值，就是拿 2026 年的答案去校准 2010 年的
筛子，等于把前视偏差从可选池挪进粗筛。故本脚本**打印召回率作为诊断，但不据此调参**。

`--as-of Y` 的口径：只用截至 `Y` 年报（次年 4 月底披露完）可得的数据，
候选表自 `Y+1`-05-01 起可用，与 `build_point_in_time_universe.py` 一致。

用法::

    python3 scripts/build_pit_attention_candidates.py --as-of 2010
    python3 scripts/build_pit_attention_candidates.py --as-of 2015 --out /tmp/c2015.csv
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "data/raw/financials"
OHLCV = ROOT / "data/raw/ohlcv"
TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
OUT_DIR = ROOT / "data/processed/pit_attention"

FIELDS = ["as_of_year", "security_code", "security_name", "listed_on", "years_listed",
          "roe_avg5", "roe_min5", "roe_years", "gross_margin", "net_margin",
          "revenue_yi", "profit_yi", "revenue_cagr", "profit_cagr",
          "today_class", "today_in_pool"]


def _num(text):
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return None


def is_a_share(code: str) -> bool:
    return code[:1] in ("0", "3", "6") and code[:2] not in ("43", "83", "87", "88", "92")


def load_annuals():
    out = defaultdict(dict)
    for path in sorted(FIN.glob("*-12-31.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row.get("notice_date") or "").strip() and is_a_share(row["security_code"]):
                    out[row["security_code"]][row["report_date"][:4]] = row
    return out


def first_traded():
    out = {}
    for path in sorted(OHLCV.glob("*.csv")):
        if path.stem.startswith("INDEX_"):
            continue
        with path.open(encoding="utf-8") as handle:
            handle.readline()
            line = handle.readline()
            if line:
                out[path.stem] = line.split(",", 1)[0]
    return out


def cagr(first: float, last: float, years: int):
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def profile(rows: dict, year: int, window: int = 5):
    """返回该公司截至 `year` 的财务画像；数据不足返回 None。"""
    years = [str(y) for y in range(year - window + 1, year + 1)]
    have = [(y, rows[y]) for y in years if y in rows]
    if len(have) < 3:
        return None
    roes = [r for _y, row in have if (r := _num(row.get("weightavg_roe"))) is not None]
    last = have[-1][1]
    revenue, profit = _num(last.get("total_operate_income")), _num(last.get("parent_netprofit"))
    first_rev = _num(have[0][1].get("total_operate_income"))
    first_pro = _num(have[0][1].get("parent_netprofit"))
    span = int(have[-1][0]) - int(have[0][0])
    return {
        "roe_avg5": statistics.fmean(roes) / 100 if roes else None,
        "roe_min5": min(roes) / 100 if roes else None,
        "roe_years": len(have),
        "gross_margin": (g / 100 if (g := _num(last.get("gross_margin"))) is not None else None),
        "net_margin": (profit / revenue if revenue and revenue > 0 and profit is not None else None),
        "revenue_yi": (revenue / 1e8 if revenue else None),
        "profit_yi": (profit / 1e8 if profit else None),
        "revenue_cagr": cagr(first_rev, revenue, span),
        "profit_cagr": cagr(first_pro, profit, span),
        "name": last.get("security_name", ""),
    }


def passes(p: dict, args) -> bool:
    """**宽松**召回门槛。命中任一「护城河可能的财务痕迹」即入候选。

    三条并联而非串联——§5 认的护城河有三种典型财务签名，任何一种都不该被另外两条挡掉：
    ① 回报型：长期 ROE 高（品牌、渠道、牌照）；
    ② 定价权型：毛利率高（专利、技术、品类垄断），即便 ROE 因扩张期投入而不高；
    ③ 规模型：营收体量大且盈利（成本曲线、网络效应），即便 ROE 与毛利率平庸。
    """
    if p["profit_yi"] is None or p["profit_yi"] <= 0:
        return False
    if (p["revenue_yi"] or 0) < args.min_revenue:
        return False
    hits = 0
    if (p["roe_avg5"] or 0) >= args.roe_gate:
        hits += 1
    if (p["gross_margin"] or 0) >= args.gross_gate:
        hits += 1
    if (p["revenue_yi"] or 0) >= args.scale_gate:
        hits += 1
    return hits >= 1


def main() -> int:
    ap = argparse.ArgumentParser(description="时点 worth_attention 候选粗筛")
    ap.add_argument("--as-of", type=int, required=True, help="截至该财年（次年 5 月起可用）")
    ap.add_argument("--window", type=int, default=5, help="财务回看年数")
    ap.add_argument("--roe-gate", type=float, default=0.12, help="回报型入选线")
    ap.add_argument("--gross-gate", type=float, default=0.35, help="定价权型入选线")
    ap.add_argument("--scale-gate", type=float, default=100.0, help="规模型入选线（亿元营收）")
    ap.add_argument("--min-revenue", type=float, default=3.0, help="营收下限（亿元），挡掉微型公司")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    annuals, listed = load_annuals(), first_traded()
    triage = {r["security_code"]: r["attention_class"]
              for r in csv.DictReader(TRIAGE.open(encoding="utf-8"))}
    cutoff = f"{args.as_of}-12-31"

    alive, rows_out, wa_listed, wa_kept = [], [], [], []
    for code, rows in annuals.items():
        day = listed.get(code)
        if day is None or day > cutoff:
            continue
        alive.append(code)
        p = profile(rows, args.as_of, args.window)
        if p is None:
            continue
        is_wa = triage.get(code) == "worth_attention"
        if is_wa:
            wa_listed.append(code)
        if not passes(p, args):
            continue
        if is_wa:
            wa_kept.append(code)
        rows_out.append({
            "as_of_year": args.as_of, "security_code": code, "security_name": p["name"],
            "listed_on": day, "years_listed": f"{(args.as_of - int(day[:4])):d}",
            "roe_avg5": f"{p['roe_avg5']:.4f}" if p["roe_avg5"] is not None else "",
            "roe_min5": f"{p['roe_min5']:.4f}" if p["roe_min5"] is not None else "",
            "roe_years": p["roe_years"],
            "gross_margin": f"{p['gross_margin']:.4f}" if p["gross_margin"] is not None else "",
            "net_margin": f"{p['net_margin']:.4f}" if p["net_margin"] is not None else "",
            "revenue_yi": f"{p['revenue_yi']:.2f}" if p["revenue_yi"] is not None else "",
            "profit_yi": f"{p['profit_yi']:.2f}" if p["profit_yi"] is not None else "",
            "revenue_cagr": f"{p['revenue_cagr']:.4f}" if p["revenue_cagr"] is not None else "",
            "profit_cagr": f"{p['profit_cagr']:.4f}" if p["profit_cagr"] is not None else "",
            "today_class": triage.get(code, "**未三类化**"),
            "today_in_pool": "1" if is_wa else "0",
        })

    out = args.out or (OUT_DIR / f"candidates_{args.as_of}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    rows_out.sort(key=lambda r: -float(r["roe_avg5"] or 0))
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"=== 时点候选粗筛｜截至 {args.as_of} 年报（{args.as_of + 1}-05-01 起可用）===")
    print(f"门槛（**并联，命中任一即入**）：近 {args.window} 年均 ROE ≥{args.roe_gate:.0%}"
          f" ／ 毛利率 ≥{args.gross_gate:.0%} ／ 营收 ≥{args.scale_gate:.0f}亿"
          f"；前置：净利>0 且营收 ≥{args.min_revenue:.0f}亿")
    print(f"当时已上市 A 股 {len(alive):,} 家 → **候选 {len(rows_out):,} 家**"
          f"（{len(rows_out) / len(alive):.1%}）")
    kept = sum(1 for r in rows_out if r["today_in_pool"] == "1")
    if wa_listed:
        print(f"**召回诊断**（仅诊断，不据此调参）：当时已上市的今日 worth_attention 共 "
              f"{len(wa_listed)} 家，粗筛留下 {len(wa_kept)} 家 → **召回 {len(wa_kept)/len(wa_listed):.1%}**")
        missed = sorted(set(wa_listed) - set(wa_kept))
        if missed:
            names = {c: annuals[c][max(annuals[c])].get("security_name", c) for c in missed}
            print(f"  漏掉的 {len(missed)} 家：" + "、".join(f"{names[c]}({c})" for c in missed[:15])
                  + ("…" if len(missed) > 15 else ""))
    print(f"候选中今日仍在 261 池的 {kept} 家，**其余 {len(rows_out) - kept} 家是待判断的重点**"
          f"——它们当年同样够格进候选，今天却不在名单里")
    print(f"\n{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

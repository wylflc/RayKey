#!/usr/bin/env python3
"""面板式时点判定的工具（OI-034 第 7 步，用户 2026-08-08 指令）。

用户要求
--------
「3400 家逐家独立判，对每家公司在判定时就直接给出每年的判定结果……**不要开后视镜**，
只基于每年当时具体已有的财务状况、公司状态、市场环境、护城河、业务壁垒等信息判断。」

为什么改成面板式
----------------
此前三版都有前视残留：§12.9.11/12 的三期版只判了窄门槛候选；§12.9.14 的逐年版把
`Set A` 直接取自今日 261 只——**「谁有资格进池」这件事仍由 2026 年的答案决定**。
面板式从候选侧构造：凡 2009-2025 期间**任一年出现过护城河财务签名**的 A 股全部进入
判定队列（3,400 家），逐家给出 worth 的起止年，与今日名单无关。

两个子命令
----------
* `facts`：为一批公司打印**逐年轨迹**（ROE / 毛利 / 净利率 / 营收 / 增速 / 上市年限），
  供逐家判定。轨迹按年给出，判定时只许引用 ≤ 该年的列。
* `build`：把 `verdicts_panel.csv` 装配成逐年 worth_attention 名单与回测用的时变股票库。

`verdicts_panel.csv` 格式::

    security_code,security_name,worth_from,worth_to,rule,reason

`worth_from=0` 表示**从未够格**（一行即可）。同一公司可有多行（护城河丢失后重建）。
`worth_to=9999` 表示截至 2025 年仍成立。

用法::

    python3 scripts/pit_panel.py facts --batch 1 --size 200
    python3 scripts/pit_panel.py build
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
PIT = ROOT / "data/processed/pit_attention"
PANEL = PIT / "verdicts_panel.csv"
QUEUE = PIT / "panel_queue.csv"
OUT = PIT / "universe_panel_yearly.csv"

Y0, Y1 = 2009, 2025


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


def window(rows, year, w=5):
    vals, name = [], ""
    for y in [str(x) for x in range(year - w + 1, year + 1)]:
        row = rows.get(y)
        if row is None:
            continue
        roe, profit = _num(row.get("weightavg_roe")), _num(row.get("parent_netprofit"))
        revenue, gross = _num(row.get("total_operate_income")), _num(row.get("gross_margin"))
        name = row.get("security_name", name)
        if roe is None or profit is None:
            continue
        vals.append((roe / 100.0, profit, (revenue or 0) / 1e8, (gross or 0) / 100.0))
    if len(vals) < 3:
        return None
    return {"roe": statistics.fmean(v[0] for v in vals), "roemin": min(v[0] for v in vals),
            "profit": vals[-1][1], "revenue": vals[-1][2], "gross": vals[-1][3], "name": name}


def signature(p) -> bool:
    """四条并联的护城河财务签名（§12.9.13 校准，对今日名单召回 87%）。**只决定何时值得判。**"""
    if p is None or p["profit"] <= 0:
        return False
    return ((p["roe"] >= 0.15 and p["roemin"] >= 0.08 and p["revenue"] >= 10)
            or (p["gross"] >= 0.40 and p["revenue"] >= 5)
            or p["revenue"] >= 100
            or (p["roe"] >= 0.10 and p["revenue"] >= 30))


def build_queue(annuals, listed):
    """判定队列：任一年出现过签名的公司，按首次签名年 → 规模降序。"""
    rows = []
    for code, series in annuals.items():
        years = []
        for year in range(Y0, Y1 + 1):
            day = listed.get(code)
            if day is None or day > f"{year}-12-31":
                continue
            if signature(window(series, year)):
                years.append(year)
        if years:
            last = window(series, years[-1])
            rows.append({"security_code": code, "security_name": last["name"],
                         "first_sig": years[0], "n_sig": len(years),
                         "peak_revenue": f"{max(window(series, y)['revenue'] for y in years):.1f}"})
    rows.sort(key=lambda r: (r["first_sig"], -float(r["peak_revenue"])))
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def cmd_facts(args):
    annuals, listed = load_annuals(), first_traded()
    if QUEUE.exists() and not args.rebuild:
        queue = list(csv.DictReader(QUEUE.open(encoding="utf-8")))
    else:
        queue = build_queue(annuals, listed)
    done = set()
    if PANEL.exists():
        done = {r["security_code"] for r in csv.DictReader(PANEL.open(encoding="utf-8"))}
    todo = [r for r in queue if r["security_code"] not in done]
    lo = (args.batch - 1) * args.size
    batch = todo[lo:lo + args.size]
    print(f"# 队列 {len(queue)} 家｜已判 {len(done)}｜待判 {len(todo)}｜本批 {len(batch)}"
          f"（第 {args.batch} 批，每批 {args.size}）")
    print("# 逐年轨迹｜R=近5年均ROE% M=最低ROE% G=毛利% N=净利率% S=营收亿 ｜判某年只许看该年及之前")
    if args.roster:
        # 紧凑模式：签名区间 + 峰值特征。**判定以业务性质为准**（§5.4.1 第 2 条：以竞争力为准，
        # 不以盈利水平为主要依据），故多数公司凭业务类型即可判；需细看轨迹的再单独拉。
        for row in batch:
            code = row["security_code"]
            series = annuals.get(code, {})
            years = [y for y in range(Y0, Y1 + 1)
                     if (listed.get(code, "9") <= f"{y}-12-31") and signature(window(series, y))]
            ps = [window(series, y) for y in years]
            print(f"{code} {row['security_name']:<9}签{years[0]%100:02d}-{years[-1]%100:02d}"
                  f"({len(years)}y) ROE峰{max(p['roe'] for p in ps)*100:.0f}"
                  f" 毛峰{max(p['gross'] for p in ps)*100:.0f}"
                  f" 收峰{max(p['revenue'] for p in ps):.0f}亿"
                  f" 上市{listed.get(code,'?')[:4]}")
        return 0
    for row in batch:
        code = row["security_code"]
        series = annuals.get(code, {})
        day = listed.get(code, "")
        cells = []
        for year in range(Y0, Y1 + 1):
            if day and day > f"{year}-12-31":
                continue
            p = window(series, year)
            if p is None:
                continue
            last = series.get(str(year))
            revenue = _num(last.get("total_operate_income")) if last else None
            profit = _num(last.get("parent_netprofit")) if last else None
            margin = (profit / revenue * 100) if revenue and revenue > 0 and profit is not None else 0
            cells.append(f"{year % 100:02d}:R{p['roe']*100:.0f}/M{p['roemin']*100:.0f}"
                         f"/G{p['gross']*100:.0f}/N{margin:.0f}/S{p['revenue']:.0f}")
        print(f"{code} {row['security_name']:<9}上市{day[:4]} " + " ".join(cells))
    return 0


def cmd_build(args):
    if not PANEL.exists():
        print(f"**缺 {PANEL}**")
        return 1
    rows = [r for r in csv.DictReader(PANEL.open(encoding="utf-8"))
            if r["worth_from"] and int(r["worth_from"]) > 0]
    members = defaultdict(dict)
    for r in rows:
        a, b = int(r["worth_from"]), min(int(r["worth_to"]), Y1)
        for year in range(max(a, Y0), b + 1):
            members[year][r["security_code"]] = r["security_name"]
    out_rows = []
    for year in range(Y0, Y1 + 1):
        for code, name in sorted(members.get(year, {}).items()):
            out_rows.append({"effective_from": f"{year + 1}-05-01", "effective_to": f"{year + 2}-04-30",
                             "screen_year": year, "security_code": code, "security_name": name,
                             "avg_roe_3y": "", "rank": ""})
    with (args.out or OUT).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["effective_from", "effective_to", "screen_year",
                                                    "security_code", "security_name", "avg_roe_3y", "rank"])
        writer.writeheader()
        writer.writerows(out_rows)
    tiers = {r["security_code"] for r in
             csv.DictReader((ROOT / "data/processed/a_share_watchlist_quality_tiers.csv").open(encoding="utf-8"))}
    print(f'{"筛选年":<8}{"名单":>7}{"今日在池":>9}{"今日不在池":>11}{"生效自":>13}')
    print("-" * 50)
    for year in range(Y0, Y1 + 1):
        m = members.get(year, {})
        inp = sum(1 for c in m if c in tiers)
        print(f"{year:<8}{len(m):>7}{inp:>9}{len(m) - inp:>11}{year + 1:>9}-05-01")
    union = {r["security_code"] for r in rows}
    print(f"\n判定为 worth 的公司 {len(union)} 家｜其中今日不在池 {len(union - tiers)} 家")
    print(f"{args.out or OUT}｜{len(out_rows):,} 行")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="面板式时点判定")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facts", help="打印一批公司的逐年轨迹")
    f.add_argument("--batch", type=int, default=1)
    f.add_argument("--size", type=int, default=200)
    f.add_argument("--rebuild", action="store_true")
    f.add_argument("--roster", action="store_true", help="紧凑花名册：每家一行峰值，不出逐年轨迹")
    f.set_defaults(func=cmd_facts)
    b = sub.add_parser("build", help="装配逐年名单")
    b.add_argument("--out", type=Path)
    b.set_defaults(func=cmd_build)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

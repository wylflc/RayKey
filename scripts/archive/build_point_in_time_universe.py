#!/usr/bin/env python3
"""时点股票库：每年只用**当时已披露**的年报重筛一次，输出逐年成员表。

为什么要有它
------------
§12.9 的全部回测都以**今天的 261 只**为可选池，而这 261 只是 2026 年选出来的——
当年会入选、后来质量下滑或暴雷而被剔除的公司，回测一次都没持有过。
§12.9.9 已把这个偏差测到 **年化 5.64pp**（2010 cohort：进池组 9.4%／亏损率 10%，
未进池组 3.8%／**亏损率 45%**）。本脚本从根上去掉它：**每年重筛，只用当年可得的数据。**

筛选口径（§5 质量分层的定量代理，刻意从简——§5 真正的护城河判断无法回放）
--------------------------------------------------------------------
* **排序键**：近 3 个财年加权 ROE 的均值。质量的核心代理。
* **硬门槛**：3 年每年 ROE ≥ 10%、净利率 ≥ 5%、净利润为正、3 年年报齐备。
* **缓冲规则**：**进榜看前 200、出榜看跌出 350**。
  没有缓冲的话，排名在 200 名上下抖动的公司会年年进出，制造大量与基本面无关的换手；
  缓冲带把股票库稳定在 200~300 只（用户指定的规模），这也是主流指数编制的通行做法。
* **生效时点**：`Y` 年的年报要到 `Y+1` 年 4 月底才披露完，故 `Y` 年的名单
  **从 `Y+1`-05-01 起生效**，到下一份名单生效前一日为止。**这是不可提前的。**

板块过滤
--------
`RPT_LICO_FN_CPD` 含新三板（43/83/87/88/92 开头）。§12.4.2 记过这一点，
`analyze_survivorship_bias.py` 首版仍漏掉，后果是 2020 年那次筛选 831 家里
**417 家（50.2%）是新三板**，把入池率压到 6.4%（实为 12.9%）。此处一并过滤。

用法::

    python3 scripts/build_point_in_time_universe.py
    python3 scripts/build_point_in_time_universe.py --enter 200 --exit 350 --roe-min 0.10
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
OUT = ROOT / "data/processed/point_in_time_universe.csv"

FIELDS = ["effective_from", "effective_to", "screen_year", "security_code",
          "security_name", "avg_roe_3y", "rank"]


def _num(text: str | None) -> float | None:
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return None


def is_a_share(code: str) -> bool:
    return code[:1] in ("0", "3", "6") and code[:2] not in ("43", "83", "87", "88", "92")


def load_annuals() -> dict[str, dict[str, dict]]:
    """{代码: {财年: 行}}，只取**已披露**的年报（`notice_date` 非空）。"""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in sorted(FIN.glob("*-12-31.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row.get("notice_date") or "").strip() and is_a_share(row["security_code"]):
                    out[row["security_code"]][row["report_date"][:4]] = row
    return out


def first_traded() -> dict[str, str]:
    """{代码: 首个交易日}。用于把**上市前的报表**挡在筛选之外，见 `score` 的说明。"""
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


def score(annuals, year: int, years: int, roe_min: float, margin_min: float,
          listed: dict[str, str] | None = None, gross_min: float = 0.0,
          stability: float = 0.0):
    """返回 [(近 3 年平均 ROE, 代码, 名称)]，已按 ROE 降序。

    **上市前报表必须剔除。** `RPT_LICO_FN_CPD` 含招股书期间的报表，次新股上市前股本极小、
    ROE 虚高，按 ROE 排名会轻松挤进前 200；而估值带的归一化 ROE（5 年中位）读的是同一批
    虚高值，V 随之高估、P/V 显得便宜。**筛选与估值在同一个方向上出错，于是成为系统性陷阱**：
    首版口径下建仓时上市中位仅 **1.3 年**、**68% 的资金投向上市不足 3 年的公司**
    （对照：261 池版本 11.9%），16 年年化 −0.19%。
    要求回看窗口内的年报全部在上市之后，即首个交易日早于窗口第一个财年年初。
    """
    ranked = []
    for code, rows in annuals.items():
        window = [str(y) for y in range(year - years + 1, year + 1)]
        if listed is not None:
            day = listed.get(code)
            if day is None or day >= f"{window[0]}-01-01":
                continue
        roes, ok = [], True
        for y in window:
            row = rows.get(y)
            if row is None:
                ok = False
                break
            roe, profit = _num(row.get("weightavg_roe")), _num(row.get("parent_netprofit"))
            revenue = _num(row.get("total_operate_income"))
            if roe is None or profit is None or profit <= 0 or roe / 100.0 < roe_min:
                ok = False
                break
            # 净利率门槛：营收缺失时不作否决——早年部分行缺 `total_operate_income`，
            # 用缺失去否决等于按数据完整度选股，而不是按质量选股。
            if revenue and revenue > 0 and profit / revenue < margin_min:
                ok = False
                break
            # 毛利率门槛。**银行该表无毛利率**，故 `gross_min>0` 会连带把银行剔除——
            # 这是有意的：残余收益模型用归一化 ROE 驱动，而银行的 ROE 由杠杆与监管资本
            # 决定，账面净资产的经济含义与实业公司不同，同一套带套在银行上并不成立。
            gross = _num(row.get("gross_margin"))
            if gross_min > 0 and (gross is None or gross / 100.0 < gross_min):
                ok = False
                break
            roes.append(roe / 100.0)
        if ok and len(roes) == years:
            # 稳定性罚项：ROE 高但年际起落大的，多半是周期或一次性收益，不是护城河。
            penalty = statistics.pstdev(roes) * stability if stability and len(roes) > 1 else 0.0
            ranked.append((statistics.fmean(roes) - penalty, code,
                           rows[window[-1]]["security_name"]))
    ranked.sort(reverse=True)
    return ranked


def main() -> int:
    ap = argparse.ArgumentParser(description="时点股票库（每年重筛）")
    ap.add_argument("--first-year", type=int, default=2009, help="第一个筛选财年")
    ap.add_argument("--roe-years", type=int, default=3, help="ROE 回看年数")
    ap.add_argument("--roe-min", type=float, default=0.10, help="每年 ROE 下限")
    ap.add_argument("--margin-min", type=float, default=0.05, help="每年净利率下限")
    ap.add_argument("--enter", type=int, default=200, help="进榜名次（缓冲带下沿）")
    ap.add_argument("--exit", dest="exit_rank", type=int, default=350, help="出榜名次（缓冲带上沿）")
    ap.add_argument("--gross-margin-min", type=float, default=0.0,
                    help="每年毛利率下限；>0 会连带剔除银行（该表银行无毛利率字段）")
    ap.add_argument("--stability", type=float, default=0.0,
                    help="排序键减去 该系数×ROE年际标准差，惩罚不稳定的高 ROE")
    ap.add_argument("--allow-pre-listing", action="store_true",
                    help="不剔除上市前报表（复现首版口径用，见 score 的说明）")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    annuals = load_annuals()
    listed = None if args.allow_pre_listing else first_traded()
    last_year = max((y for rows in annuals.values() for y in rows), default="2025")
    years = list(range(args.first_year, int(last_year) + 1))

    members: set[str] = set()
    rows_out, history = [], []
    for year in years:
        ranked = score(annuals, year, args.roe_years, args.roe_min, args.margin_min,
                       listed, args.gross_margin_min, args.stability)
        rank_of = {code: i + 1 for i, (_r, code, _n) in enumerate(ranked)}
        # 缓冲：已在库的只要没跌出 `exit_rank` 就留下；不在库的须进 `enter` 才收。
        kept = {c for c in members if rank_of.get(c, 10 ** 9) <= args.exit_rank}
        added = {c for _r, c, _n in ranked[:args.enter]}
        members = kept | added
        eff_from = f"{year + 1}-05-01"
        eff_to = f"{year + 2}-04-30"
        for roe, code, name in ranked:
            if code in members:
                rows_out.append({"effective_from": eff_from, "effective_to": eff_to,
                                 "screen_year": year, "security_code": code,
                                 "security_name": name, "avg_roe_3y": f"{roe:.4f}",
                                 "rank": rank_of[code]})
        history.append((year, len(ranked), len(members), len(added - kept), len(kept - added)))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"时点股票库｜近 {args.roe_years} 年 ROE≥{args.roe_min:.0%} 且净利率≥{args.margin_min:.0%}"
          f"｜进榜前 {args.enter}／跌出 {args.exit_rank} 才出榜")
    print(f'{"筛选年":<8}{"合格家数":>9}{"库内":>7}{"新进":>7}{"移出":>7}{"生效自":>13}')
    print("-" * 52)
    for year, n_pass, n_mem, n_add, n_drop in history:
        print(f"{year:<8}{n_pass:>9}{n_mem:>7}{n_add:>7}{n_drop:>7}{year + 1:>9}-05-01")
    union = {r["security_code"] for r in rows_out}
    print(f"\n{args.out}｜{len(rows_out):,} 行｜历年并集 **{len(union):,} 只**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fetch dividend history and derive shareholder-return metrics (工作流 §6.5.3, OI-008).

Closes the gap where 股东回报 sat outside every band method: §6.5.3 mandates the
A-1 caliber (可分配现金 ÷ 要求回报) alongside A-2, and K's primary is a Gordon DDM,
but neither ever ran because dividend data was not in `valuation_evidence`.

Two derived quantities, both from the same endpoint:

* **年度现金分红总额** = Σ(每 10 股派息 ÷ 10 × 当期总股本) over one report year,
  including interim dividends.
* **回购注销率** = 股本净减少 ÷ 期初股本. Buyback *cancellation* is what changes
  per-share value, and it shows up directly as a falling share count — no separate
  repurchase endpoint needed (Eastmoney exposes none that responds).

Usage::

    python3 scripts/fetch_a_share_dividends.py --codes 000333,300750
    python3 scripts/fetch_a_share_dividends.py --all
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_OUT = ROOT / "data/interim/a_share_dividends.csv"
API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
COLUMNS = "SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,PRETAX_BONUS_RMB,TOTAL_SHARES,PLAN_NOTICE_DATE,ASSIGN_PROGRESS"


def fetch_one(code: str, timeout: float = 15.0) -> list[dict]:
    query = urllib.parse.urlencode({
        "reportName": "RPT_SHAREBONUS_DET",
        "columns": COLUMNS,
        "pageSize": "60",
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "filter": f'(SECURITY_CODE="{code}")',
    })
    request = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return ((payload.get("result") or {}).get("data")) or []


# --------------------------------------------------------------- 除权除息日检出（工作流 §11.4，结 OI-030）
#
# §11.4 要求「除权除息日按交易所除权参考价公式调整带、止损价与 `cost_basis`」与
# `cost_basis`」，但全流程原先没有任何一处会去发现「今天是某只持仓的除权除息日」——清单
# 手工维护、§9.1 五步里没有这一步、`track_holdings_daily.py` 也不读除权数据。
#
# v2.56：割肉价已退役，本检出的对象改为**估值带与 P/V**——除权日现价跳而带不动，P/V 凭空
# 变小会造出假买入信号（10送10 直接腰斩），且偏差发生在**全池**而非仅持仓。
# 实测判例（2026-08-07）：九号公司当日除权除息，两次跑批都拿未调整的割肉价 41.00 与除权后
# 价格比较，输出「跌破 41.00」的**假触及**，并把除权造成的价格下跳读成「当日跌幅居持仓之首」。
# 代价是双向的：现金分红当日产生假警报，而送转/配股（因子远大于分红）当日会反向产生**假安全**
# ——调整后的割肉价本应大幅下移，未调整则显示为「远未触及」。
#
# 检出 + 提示、不自动改：脚本负责发现并算出建议值，持仓表的写回由维护者完成（§11.4：
# 带由建带链机械维护，持仓表是人工侧）。

EX_DIV_COLUMNS = (
    "SECURITY_CODE,SECURITY_NAME_ABBR,EX_DIVIDEND_DATE,IMPL_PLAN_PROFILE,"
    "PRETAX_BONUS_RMB,BONUS_RATIO,IT_RATIO,ASSIGN_PROGRESS"
)


def fetch_ex_dividend_events(as_of: str, timeout: float = 15.0) -> dict[str, dict[str, object]]:
    """取 `as_of` 当日全市场除权除息事件，返回 {代码: {计划文本, 每股现金, 每股送转}}。

    按日过滤而非逐票查询：一次请求即可拿到当日全市场（实测 2026-08-07 共 15 家），
    与持仓取交集在本地做，故每日只多一次网络往返。
    """
    query = urllib.parse.urlencode({
        "reportName": "RPT_SHAREBONUS_DET",
        "columns": EX_DIV_COLUMNS,
        "pageSize": "500",
        "sortColumns": "SECURITY_CODE",
        "sortTypes": "1",
        "filter": f"(EX_DIVIDEND_DATE='{as_of}')",
    })
    request = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = ((payload.get("result") or {}).get("data")) or []

    events: dict[str, dict[str, object]] = {}
    for row in rows:
        code = str(row.get("SECURITY_CODE") or "").zfill(6)
        if not code:
            continue
        cash_per_ten = float(row.get("PRETAX_BONUS_RMB") or 0)
        share_per_ten = float(row.get("BONUS_RATIO") or 0) + float(row.get("IT_RATIO") or 0)
        events[code] = {
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "plan": row.get("IMPL_PLAN_PROFILE", ""),
            "cash_per_share": cash_per_ten / 10,
            "share_ratio": share_per_ten / 10,
            "progress": row.get("ASSIGN_PROGRESS", ""),
        }
    return events


def adjust_for_ex_dividend(price: float, cash_per_share: float, share_ratio: float) -> float:
    """除权除息价格换算：`(原价 − 每股现金红利) ÷ (1 + 每股送转比例)`。

    该换算是**价格口径换算**（§11.4 的交易所除权参考价公式），不属于任何规则变更。
    """
    return (price - cash_per_share) / (1 + share_ratio)


def summarise(code: str, rows: list[dict]) -> list[dict]:
    """按报告年汇总：现金分红总额、期末股本、回购注销率。"""
    by_year: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not row.get("REPORT_DATE"):
            continue
        # 只计已实施的分配；预案未实施的不作既成事实（§6.5.3 要求"可持续、可兑现"）
        if row.get("ASSIGN_PROGRESS") and "不分配" in str(row["ASSIGN_PROGRESS"]):
            continue
        by_year[row["REPORT_DATE"][:4]].append(row)

    out: list[dict] = []
    years = sorted(by_year, reverse=True)
    shares_by_year: dict[str, float] = {}
    for year in years:
        entries = sorted(by_year[year], key=lambda r: r.get("REPORT_DATE") or "")
        cash = 0.0
        for entry in entries:
            per_ten = entry.get("PRETAX_BONUS_RMB")
            shares = entry.get("TOTAL_SHARES")
            if per_ten and shares:
                cash += float(per_ten) / 10 * float(shares)
        last_shares = next((float(e["TOTAL_SHARES"]) for e in reversed(entries)
                            if e.get("TOTAL_SHARES")), None)
        if last_shares:
            shares_by_year[year] = last_shares
        out.append({
            "security_code": code,
            "security_name": entries[0].get("SECURITY_NAME_ABBR", ""),
            "report_year": year,
            "cash_dividend_total": f"{cash:.0f}" if cash else "",
            "total_shares": f"{last_shares:.0f}" if last_shares else "",
            "buyback_cancel_rate": "",
            # 只有含年报（12-31）分配的年份才是完整年度口径；当年只有中期分配的
            # 行是部分年度，直接当年度分红会低估（判例：宁德时代 2026 行仅 65.3 亿）。
            "has_annual": "true" if any(str(e.get("REPORT_DATE", ""))[5:10] == "12-31" for e in entries) else "",
            "source": "eastmoney RPT_SHAREBONUS_DET",
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    # 回购注销率 = 股本净减少 ÷ 上一年期末股本（股本增加=送转/增发，不计为注销）
    for row in out:
        year = row["report_year"]
        prior = shares_by_year.get(str(int(year) - 1))
        current = shares_by_year.get(year)
        if prior and current and current < prior:
            row["buyback_cancel_rate"] = f"{(prior - current) / prior:.6f}"
        elif prior and current:
            row["buyback_cancel_rate"] = "0"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="取分红历史并派生股东回报口径（OI-008）")
    parser.add_argument("--codes", help="逗号分隔的 6 位代码")
    parser.add_argument("--all", action="store_true", help="取估值表全量")
    parser.add_argument("--valuation", type=Path, default=DEFAULT_VALUATION)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sleep", type=float, default=0.12)
    args = parser.parse_args()

    if args.all:
        with args.valuation.open(encoding="utf-8-sig") as handle:
            codes = [r["security_code"].zfill(6) for r in csv.DictReader(handle)]
    elif args.codes:
        codes = [c.strip().zfill(6) for c in args.codes.split(",") if c.strip()]
    else:
        parser.error("须给 --codes 或 --all")

    records: list[dict] = []
    failed: list[str] = []
    for index, code in enumerate(codes, 1):
        try:
            records.extend(summarise(code, fetch_one(code)))
        except Exception as error:                       # noqa: BLE001
            failed.append(f"{code}:{type(error).__name__}")
        if index % 50 == 0:
            print(f"  {index}/{len(codes)} …")
        time.sleep(args.sleep)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["security_code", "security_name", "report_year", "cash_dividend_total",
              "total_shares", "buyback_cancel_rate", "has_annual", "source", "retrieved_at_utc"]
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    covered = len({r["security_code"] for r in records})
    print(f"分红取数：{len(codes)} 只请求，{covered} 只有分红记录，共 {len(records)} 行 → {args.out}")
    if failed:
        print(f"  失败 {len(failed)}：{failed[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

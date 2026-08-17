#!/usr/bin/env python3
"""逐季度历史财务数据（全市场，含公告日），为 OI-034 的历史估值带提供输入。

为什么需要它
------------
OI-034 的回测方案（用户 2026-08-07 给定）第 1 步是：**对每个股票，每年四次定期报告，
基于每次定期报告计算一个估值带**，每个带对应一段生效时间，从而使每个股票的每一天都有
对应的估值状态。而本仓库此前**只有最新一期**的估值证据——`a_share_valuation_dossiers.csv`
只存当前带，历史带从未存在过。

**这一步的价值大于回测本身**：它消除 §12.4 的**估值闸门前视豁免**。v2.13 为量价信号回放
开出该豁免（允许用**当前**的带与分层还原历史某天的矩阵资格，明知含前视仍照用），代价是
此后全部回放的绝对收益只能当上界读（§12.7 第 2 条读数义务）。有了逐季历史财务，历史带
可以按**当时已披露的数据**重建，豁免就不必再吃。

`NOTICE_DATE` 是本表最要紧的一列
--------------------------------
§12.4 硬约束：回放使用的每条证据必须满足 `available_at <= 回放日`，而 `available_at` 是
**公告日**、不是报告期末。2026Q1 的报告期末是 03-31，但公告日可能落在 04-28——**在 4 月
中旬用 Q1 数据建带就是前视**。故本表逐行记 `notice_date`，下游按它决定某个带从哪天起生效。

顺带缓解幸存者偏差
------------------
按**报告期**取全市场，取到的是**当时在市**的公司，包含此后已退市的。实测 2022-03-31 有
**5,921** 行、而 2026-03-31 只有 5,893 行——差额正是那批已退市/已更名的公司。这比"只取
今天还在名单里的 261 家"严谨得多。**但只解决了基本面这一半**：`data/raw/ohlcv/` 的行情
仍只覆盖当前池与持仓（§12.4.1 已登记），完整解决须另取退市股行情。

数据源
------
东财 `RPT_LICO_FN_CPD`（业绩报表），与 `fetch_a_share_report_disclosures.py` 同源、同键名
约定（报告期列名为 `REPORTDATE` 无下划线）。实测该表历史期可取，且含建带所需的全部输入：
`PARENT_NETPROFIT`／`TOTAL_OPERATE_INCOME`／`BASIC_EPS`／`DEDUCT_BASIC_EPS`／`BPS`／
**`WEIGHTAVG_ROE`**（§6.5.7.1 的核心输入）／`XSMLL` 毛利率／`MGJYXJJE` 每股经营现金流。

用法::

    python3 scripts/fetch_a_share_quarterly_financials.py --as-of 2026-08-07
    python3 scripts/fetch_a_share_quarterly_financials.py --as-of 2026-08-07 --since 2020-03-31
    python3 scripts/fetch_a_share_quarterly_financials.py --as-of 2026-08-07 --refresh   # 重取已有期
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/raw/financials"
API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
PAGE_SIZE = 500

# 东财列名 → 本表列名。**只取建带用得上的**，不做无差别 ALL 落盘。
COLUMN_MAP = {
    "SECURITY_CODE": "security_code",
    "SECURITY_NAME_ABBR": "security_name",
    "REPORTDATE": "report_date",
    "NOTICE_DATE": "notice_date",
    "PARENT_NETPROFIT": "parent_netprofit",
    "TOTAL_OPERATE_INCOME": "total_operate_income",
    "BASIC_EPS": "basic_eps",
    "DEDUCT_BASIC_EPS": "deduct_basic_eps",
    "BPS": "bps",
    "WEIGHTAVG_ROE": "weightavg_roe",
    "XSMLL": "gross_margin",
    "MGJYXJJE": "op_cashflow_ps",
    "SJLTZ": "netprofit_yoy",
    "YSTZ": "revenue_yoy",
    "SJLHZ": "netprofit_qoq",
    "YSHZ": "revenue_qoq",
}
FIELDNAMES = list(COLUMN_MAP.values()) + ["source", "retrieved_at_utc"]

QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def quarter_ends_between(since: date, until: date) -> list[str]:
    """`since`~`until` 之间**已结束**的报告期末，升序。"""
    out = []
    for year in range(since.year, until.year + 1):
        for month, day in QUARTER_ENDS:
            end = date(year, month, day)
            if since <= end <= until:
                out.append(end.isoformat())
    return out


def fetch_period(report_date: str, timeout: float, pause: float) -> tuple[list[dict[str, str]], str | None]:
    """取某报告期的全市场行；返回 (行, 错误)。分页取尽，缺页即报错不静默。"""
    rows: list[dict[str, str]] = []
    page, pages = 1, None
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    while True:
        query = urllib.parse.urlencode({
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "ALL",
            "pageSize": str(PAGE_SIZE),
            "pageNumber": str(page),
            "sortColumns": "SECURITY_CODE",
            "sortTypes": "1",
            "filter": f"(REPORTDATE='{report_date}')",
        })
        request = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return rows, f"第 {page} 页失败（{type(exc).__name__}）"
        result = payload.get("result") or {}
        pages = pages if pages is not None else result.get("pages")
        data = result.get("data") or []
        if not data:
            break
        for item in data:
            row = {dest: ("" if item.get(src) is None else str(item[src]))
                   for src, dest in COLUMN_MAP.items()}
            row["security_code"] = row["security_code"].zfill(6)
            row["report_date"] = (row["report_date"] or "")[:10]
            row["notice_date"] = (row["notice_date"] or "")[:10]
            row["source"] = "eastmoney RPT_LICO_FN_CPD"
            row["retrieved_at_utc"] = now
            rows.append(row)
        if pages and page >= int(pages):
            break
        page += 1
        time.sleep(pause)
    return rows, None


# 法定披露截止日：一季报 4-30、半年报 8-31、三季报 10-31、年报次年 4-30。
# **披露窗未关的报告期，磁盘上那份文件必然是残缺的**——首次抓取时多数公司还没披露。
# 而残缺文件与完整文件在磁盘上无法区分，`--refresh` 又默认关闭，于是
# 「抓过一次」＝「永远停在那一次的覆盖面」。2026-08-17 实测到这个形态：
# 2026-06-30 期停在 8-11 抓的 538 家（贵州茅台 8-15 披露的半年报因此始终进不来），
# 而同一天 2025-06-30 期有 11,583 家。故窗口未关的期一律强制重取，不由 `--refresh` 决定。
DEADLINE_BY_MONTH_DAY = {"03-31": (0, 4, 30), "06-30": (0, 8, 31),
                         "09-30": (0, 10, 31), "12-31": (1, 4, 30)}


def disclosure_window_open(report_date: str, as_of: date) -> bool:
    """报告期的法定披露窗是否仍未关闭（未关 = 文件必然还在长）。"""
    year, month_day = int(report_date[:4]), report_date[5:]
    offset = DEADLINE_BY_MONTH_DAY.get(month_day)
    if offset is None:
        return False
    year_offset, month, day = offset
    return as_of <= date(year + year_offset, month, day)


def main() -> int:
    parser = argparse.ArgumentParser(description="逐季度历史财务数据全市场取数（OI-034 前置）")
    parser.add_argument("--as-of", required=True, help="截止日 YYYY-MM-DD")
    parser.add_argument("--since", default="2016-03-31", help="起始报告期末，缺省 2016-03-31（约十年）")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--refresh", action="store_true", help="重取已存在的报告期")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--pause", type=float, default=0.25)
    args = parser.parse_args()

    until = date.fromisoformat(args.as_of)
    periods = quarter_ends_between(date.fromisoformat(args.since), until)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"逐季财务取数：{args.since} → {args.as_of}，共 {len(periods)} 个报告期｜落点 {args.out_dir.relative_to(ROOT)}/")

    counts: dict[str, int] = {}
    failures: list[str] = []
    open_note: list[str] = []
    for report_date in periods:
        path = args.out_dir / f"{report_date}.csv"
        window_open = disclosure_window_open(report_date, until)
        if path.exists() and not args.refresh and not window_open:
            with path.open(newline="", encoding="utf-8") as handle:
                counts[report_date] = sum(1 for _ in csv.DictReader(handle))
            continue
        before = 0
        if path.exists():
            with path.open(newline="", encoding="utf-8") as handle:
                before = sum(1 for _ in csv.DictReader(handle))
            if window_open and not args.refresh:
                print(f"  {report_date}: 披露窗未关，强制重取（现有 {before} 家）")
        rows, error = fetch_period(report_date, args.timeout, args.pause)
        if error:
            failures.append(f"{report_date}：{error}")
        if not rows:
            failures.append(f"{report_date}：**0 行**")
            continue
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        counts[report_date] = len(rows)
        delta = f"  (+{len(rows) - before} 家)" if before else ""
        print(f"  {report_date}: {len(rows):>5} 行{delta}")
        if window_open:
            open_note.append(f"{report_date}（{len(rows)} 家，截止日前仍会增加）")
        time.sleep(args.pause)

    total = sum(counts.values())
    print(f"\n合计 {total:,} 行、{len(counts)} 个报告期")
    if open_note:
        print("⚠ **披露窗未关的报告期**：" + "；".join(open_note)
              + "。这些期每个扫描日都必须重取，覆盖面到法定截止日才定型——"
                "把它们当成完整数据用，等于系统性漏掉尚未披露的公司。")

    # §15.2 第 3 条硬自检：新增数据源必须核对**非空行数**与**每列的非空覆盖**。
    if counts:
        latest = max(counts)
        with (args.out_dir / f"{latest}.csv").open(newline="", encoding="utf-8") as handle:
            sample = list(csv.DictReader(handle))
        print(f"最新期 {latest} 逐列非空覆盖（{len(sample)} 行）：")
        for field in FIELDNAMES:
            if field in ("source", "retrieved_at_utc"):
                continue
            filled = sum(1 for row in sample if (row.get(field) or "").strip())
            mark = "  ← **整列为空**" if not filled else ""
            print(f"  {field:<22} {filled:>5}/{len(sample)}{mark}")
        # 公告日是本表存在的理由，单独把缺失说清楚
        no_notice = [r for r in sample if not (r.get("notice_date") or "").strip()]
        if no_notice:
            print(f"  ⚠ **{len(no_notice)} 行无公告日**——这些行不可用于历史建带"
                  f"（§12.4：available_at 必须是公告日），下游须显式排除而不是按报告期末凑")

    if failures:
        print(f"**失败 {len(failures)} 项**：{'；'.join(failures[:10])}" + ("…" if len(failures) > 10 else ""))
    print("  ⚠ 幸存者偏差：本表按报告期取全市场，**含当时在市、此后已退市的公司**（这一半已解决）；"
          "但 `data/raw/ohlcv/` 的行情仍只覆盖当前池与持仓，完整解决须另取退市股行情（§12.4.1）")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

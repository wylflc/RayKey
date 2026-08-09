#!/usr/bin/env python3
"""全市场 A 股个股研报抓取（OI-034 第 8 步，用户 2026-08-09 指令）。

用户要的是「每次买入节点只放行近期研报预期在增长或几乎不变的公司」。要做成
**时点可复现**的门槛，研报必须带原始发布日、且预测值是发布当时的快照——本脚本
只保存 `publishDate` 与该篇研报自带的预测字段，不引用任何当前一致预期。

数据边界（2026-08-09 实测，务必先读再用）
------------------------------------------
* 全市场按日期查询**最早只到 2017-01**；2016 及以前 `hits=0`。逐个股票查同样最早 2017。
* **预测 EPS/PE 字段只有 2024-01 之后的研报才有值**，2017-2023 全为空字符串。
  抽样 5 只大盘股 1,511 篇：2017-2023 预测 PE 有值 0 篇，2024 起 167/203。
  → 「预测值上修/持平」这个原口径**只在 2024-2025 可测**。
* 评级 `emRatingName` / `ratingChange` **2017 起全程有值**（覆盖率约 97%）。
  → 跨 2017-2025 可测的替代口径是**评级方向**，评级下调即预期下修的公开表达。

以上两条差异是数据源的事实，不是本脚本的选择。回测时哪一段用哪个口径必须显式声明。

字段来源：`reportapi.eastmoney.com/report/list`，`qType=0`（个股研报）。
`infoCode` 为研报唯一键，用于跨月切片去重。

用法::

    python3 scripts/fetch_a_share_research_reports.py                 # 2017-01 至今，跳过已存在年份
    python3 scripts/fetch_a_share_research_reports.py --from 2024-01 --refresh
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
OUT_DIR = ROOT / "data/raw/research_reports"
API = "https://reportapi.eastmoney.com/report/list"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/report/"}

FIELDS = [
    "publish_date", "security_code", "security_name", "info_code",
    "org_code", "org_sname", "report_type", "column",
    "rating_name", "rating_value", "last_rating_name", "last_rating_value", "rating_change",
    "predict_this_year_eps", "predict_next_year_eps", "predict_next_two_year_eps",
    "predict_this_year_pe", "predict_next_year_pe", "predict_next_two_year_pe",
    "aim_price", "researcher", "title", "retrieved_at_utc",
]


def month_slices(start: str, end: str):
    """按月切片。单月量级 1-2 千篇，分页深度可控（EM 深翻页不稳）。"""
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while (y, m) <= (ey, em):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        last = (date(ny, nm, 1) - date.resolution).isoformat()
        yield f"{y:04d}-{m:02d}-01", last
        y, m = ny, nm


def fetch_page(begin: str, finish: str, page: int, size: int, timeout: float, retries: int = 4):
    query = urllib.parse.urlencode({
        "industryCode": "*", "pageSize": size, "industry": "*", "rating": "", "ratingChange": "",
        "beginTime": begin, "endTime": finish, "pageNo": page, "fields": "", "qType": 0,
        "orgCode": "", "code": "", "rcode": "", "p": page, "pageNum": page,
    })
    last_error = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{begin}~{finish} p{page} 失败：{last_error}")


def normalize(row: dict, stamp: str) -> dict:
    def text(key):
        value = row.get(key)
        return "" if value is None else str(value).strip()

    return {
        "publish_date": text("publishDate")[:10],
        "security_code": text("stockCode"),
        "security_name": text("stockName"),
        "info_code": text("infoCode"),
        "org_code": text("orgCode"),
        "org_sname": text("orgSName"),
        "report_type": text("reportType"),
        "column": text("column"),
        "rating_name": text("emRatingName"),
        "rating_value": text("emRatingValue"),
        "last_rating_name": text("lastEmRatingName"),
        "last_rating_value": text("lastEmRatingValue"),
        "rating_change": text("ratingChange"),
        "predict_this_year_eps": text("predictThisYearEps"),
        "predict_next_year_eps": text("predictNextYearEps"),
        "predict_next_two_year_eps": text("predictNextTwoYearEps"),
        "predict_this_year_pe": text("predictThisYearPe"),
        "predict_next_year_pe": text("predictNextYearPe"),
        "predict_next_two_year_pe": text("predictNextTwoYearPe"),
        "aim_price": text("indvAimPriceT"),
        "researcher": text("researcher"),
        "title": text("title"),
        "retrieved_at_utc": stamp,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="全市场 A 股个股研报抓取")
    ap.add_argument("--from", dest="start", default="2017-01", help="起始月 YYYY-MM")
    ap.add_argument("--to", dest="end", default=None, help="结束月 YYYY-MM，缺省为本月")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--timeout", type=float, default=40.0)
    ap.add_argument("--sleep", type=float, default=0.25)
    ap.add_argument("--refresh", action="store_true", help="重抓已存在的年份文件")
    args = ap.parse_args()

    end = args.end or datetime.now(timezone.utc).strftime("%Y-%m")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    args.out.mkdir(parents=True, exist_ok=True)

    by_year: dict[str, dict[str, dict]] = {}
    for begin, finish in month_slices(f"{args.start}-01", f"{end}-01"):
        year = begin[:4]
        target = args.out / f"reports_{year}.csv"
        if target.exists() and not args.refresh:
            continue
        page, seen_month = 1, 0
        while True:
            payload = fetch_page(begin, finish, page, args.page_size, args.timeout)
            rows = payload.get("data") or []
            if not rows:
                break
            for row in rows:
                record = normalize(row, stamp)
                if record["info_code"]:
                    by_year.setdefault(year, {})[record["info_code"]] = record
            seen_month += len(rows)
            total_pages = int(payload.get("TotalPage") or 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(args.sleep)
        print(f"  {begin[:7]}  {seen_month:>5} 篇  累计{year}年 {len(by_year.get(year, {})):>6}", flush=True)

        # 年末落盘，避免长跑中断丢全部进度
        if begin[5:7] == "12" or (begin[:4], begin[5:7]) == (end[:4], end[5:7]):
            flush(args.out, year, by_year.pop(year, {}))

    for year in sorted(by_year):
        flush(args.out, year, by_year[year])
    return 0


def flush(out_dir: Path, year: str, records: dict[str, dict]) -> None:
    if not records:
        return
    target = out_dir / f"reports_{year}.csv"
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record in sorted(records.values(), key=lambda r: (r["publish_date"], r["security_code"])):
            writer.writerow(record)
    print(f"→ {target.name}  {len(records):,} 篇", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

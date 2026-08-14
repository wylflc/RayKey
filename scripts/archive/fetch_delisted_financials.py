#!/usr/bin/env python3
"""按证券代码逐股取主要财务指标——**补齐退市公司**（OI-040，用户 2026-08-11 指令）。

为什么需要另写一个取数器
------------------------
`fetch_a_share_quarterly_financials.py` 用 `datacenter-web.eastmoney.com` 的
`RPT_LICO_FN_CPD`，**按 `REPORTDATE` 取横截面**。该接口只返回当前在市公司：实测
康得新（002450）、华锐风电（601558）`count=null`，而茅台 `count=102`。**本地财务库
零覆盖退市公司的根因就在这里，且是静默漏掉**——横截面少了几行不会报错。

本脚本改用 `datacenter.eastmoney.com/securities` 的 F10 接口，**按 `SECUCODE` 逐股取**，
退市公司可返回（康得新现名「康得退」，21 页）。两个接口的字段值与量纲**实测逐位相同**
（茅台 2020-12-31 全字段比对），故产出可直接并入既有 `data/raw/financials/<报告期>.csv`，
下游 `pit_panel.py` / `build_historical_valuation_bands.py` 无需改动。

**时点纪律**：`NOTICE_DATE` 必须随行落库。没有公告日就无法判定该期在何时可见，
补进来的退市股会带着新的前视——这与 OI-040 要解决的问题同类。

用法::

    python3 scripts/fetch_delisted_financials.py --codes-file <每行一个代码>
    python3 scripts/fetch_delisted_financials.py --codes 002450,601558 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIN_DIR = ROOT / "data/raw/financials"
API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
REPORT = "RPT_F10_FINANCE_MAINFINADATA"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
PAGE_SIZE = 100
SOURCE = f"eastmoney {REPORT}"

# 目标列 → F10 列。**实测与 RPT_LICO_FN_CPD 同值同量纲**（茅台 2020-12-31 全字段比对）。
FIELD_MAP = {
    "security_code": "SECURITY_CODE",
    "security_name": "SECURITY_NAME_ABBR",
    "report_date": "REPORT_DATE",
    "notice_date": "NOTICE_DATE",
    "parent_netprofit": "PARENTNETPROFIT",
    "total_operate_income": "TOTALOPERATEREVE",
    "basic_eps": "EPSJB",
    "deduct_basic_eps": "EPSKCJB",
    "bps": "BPS",
    "weightavg_roe": "ROEJQ",
    "gross_margin": "XSMLL",
    "op_cashflow_ps": "MGJYXJJE",
    "netprofit_yoy": "PARENTNETPROFITTZ",
    "revenue_yoy": "TOTALOPERATEREVETZ",
    "netprofit_qoq": "DJD_DPNP_QOQ",
    "revenue_qoq": "DJD_TOI_QOQ",
}
OUT_FIELDS = [*FIELD_MAP, "source", "retrieved_at_utc"]


def secucode(code: str) -> str:
    """`002450` → `002450.SZ`。北交所 8/4/920 开头归 BJ，6 开头归 SH，其余 SZ。"""
    if code.startswith(("920", "8", "4")):
        return f"{code}.BJ"
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def fetch_code(code: str, timeout: float, pause: float, retries: int = 3) -> list[dict]:
    """取一只股票的全部期。分页直到取完；任一页失败即整只放弃（宁缺勿残）。"""
    out: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({
            "reportName": REPORT, "columns": "ALL", "pageNumber": page,
            "pageSize": PAGE_SIZE, "sortColumns": "REPORT_DATE", "sortTypes": "-1",
            "filter": f'(SECUCODE="{secucode(code)}")',
        })
        payload = None
        for attempt in range(retries):
            try:
                request = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
                payload = json.loads(urllib.request.urlopen(request, timeout=timeout).read())
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
                if attempt == retries - 1:
                    raise
                time.sleep(pause * (attempt + 2))
        result = (payload or {}).get("result")
        if not result or not result.get("data"):
            break
        out.extend(result["data"])
        if page >= (result.get("pages") or 1):
            break
        page += 1
        time.sleep(pause)
    return out


def to_row(raw: dict, stamp: str) -> dict | None:
    """F10 行 → 本地库行。缺报告期或公告日的直接丢弃——**没有公告日就没有时点**。"""
    if not raw.get("REPORT_DATE") or not raw.get("NOTICE_DATE"):
        return None
    row = {}
    for target, src in FIELD_MAP.items():
        value = raw.get(src)
        if target in ("report_date", "notice_date") and value:
            value = str(value)[:10]
        row[target] = "" if value is None else value
    row["source"] = SOURCE
    row["retrieved_at_utc"] = stamp
    return row


def load_existing(path: Path) -> tuple[list[str], list[dict], set[str]]:
    if not path.exists():
        return list(OUT_FIELDS), [], set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        header = list(reader.fieldnames or OUT_FIELDS)
    return header, rows, {r.get("security_code", "") for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="逐股取主要财务指标（补退市公司）")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--codes", help="逗号分隔代码")
    scope.add_argument("--codes-file", type=Path, help="每行一个代码")
    parser.add_argument("--out-dir", type=Path, default=FIN_DIR)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--pause", type=float, default=0.25)
    parser.add_argument("--since", default="1996-01-01", help="只保留该报告期及之后")
    parser.add_argument("--dry-run", action="store_true", help="只取数并统计，不落盘")
    args = parser.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        codes = [ln.strip() for ln in args.codes_file.read_text().splitlines() if ln.strip()]
    stamp = datetime.now(UTC).isoformat(timespec="seconds")

    by_period: dict[str, list[dict]] = defaultdict(list)
    ok = empty = failed = 0
    for index, code in enumerate(codes, 1):
        try:
            raws = fetch_code(code, args.timeout, args.pause)
        except Exception as exc:                                   # noqa: BLE001
            failed += 1
            print(f"  [{index}/{len(codes)}] {code} 失败：{type(exc).__name__}", flush=True)
            continue
        rows = [r for r in (to_row(x, stamp) for x in raws) if r and r["report_date"] >= args.since]
        if not rows:
            empty += 1
        else:
            ok += 1
            for row in rows:
                by_period[row["report_date"]].append(row)
        if index % 25 == 0 or index == len(codes):
            print(f"  [{index}/{len(codes)}] 有数据 {ok}｜无数据 {empty}｜失败 {failed}"
                  f"｜累计 {sum(len(v) for v in by_period.values()):,} 行", flush=True)
        time.sleep(args.pause)

    total_rows = sum(len(v) for v in by_period.values())
    print(f"\n取到 {total_rows:,} 行，覆盖 {len(by_period)} 个报告期，"
          f"公司 有数据 {ok}／无数据 {empty}／失败 {failed}")
    if args.dry_run:
        print("--dry-run：未落盘")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    for period, rows in sorted(by_period.items()):
        path = args.out_dir / f"{period}.csv"
        header, existing, present = load_existing(path)
        fresh = [r for r in rows if r["security_code"] not in present]
        skipped += len(rows) - len(fresh)
        if not fresh:
            continue
        for field in OUT_FIELDS:                        # 既有文件列更全时保持其列序
            if field not in header:
                header.append(field)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            for row in [*existing, *fresh]:
                writer.writerow(row)
        written += len(fresh)
    print(f"落盘 {written:,} 行；已存在跳过 {skipped:,} 行（按 报告期+代码 判重）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

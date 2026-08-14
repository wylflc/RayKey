#!/usr/bin/env python3
"""拉取港股逐年主要财务指标（东财 HKF10，免密钥公开接口）。

用途：A 股主体由港股母公司注入资产时，A 股侧只有注入后的短记录，
判定其护城河必须回到港股母体的多年记录（§5 防3.1 强制检验项要求多年 ROE）。

    python3 scripts/fetch_hk_annual_financials.py --codes 01378 --out data/interim/hk_annual_financials.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
FIELDS = [
    "security_code", "security_name", "report_date", "report_type", "currency",
    "operate_income_yi", "holder_profit_yi", "roe_avg_pct", "gross_margin_pct",
    "net_margin_pct", "bps", "basic_eps", "issued_shares", "total_parent_equity_yi",
    "debt_asset_ratio_pct", "netcash_operate_yi", "retrieved_at_utc", "source_url",
]


def fetch(code: str, timeout: float = 25.0) -> list[dict]:
    flt = urllib.parse.quote(f'(SECUCODE="{code}.HK")')
    url = (f"{API}?reportName=RPT_HKF10_FN_MAININDICATOR&columns=ALL&pageSize=80"
           f"&pageNumber=1&sortTypes=-1&sortColumns=REPORT_DATE&filter={flt}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://emweb.securities.eastmoney.com/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        payload = json.loads(fh.read())
    rows = ((payload.get("result") or {}).get("data")) or []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out = []
    for r in rows:
        rt = str(r.get("REPORT_TYPE") or "")
        if "年报" not in rt:                       # 只取年报，中报另算
            continue

        def y(key):                                # 元 → 亿元
            v = r.get(key)
            return round(v / 1e8, 2) if isinstance(v, (int, float)) else ""

        out.append({
            "security_code": code,
            "security_name": r.get("SECURITY_NAME_ABBR", ""),
            "report_date": str(r.get("REPORT_DATE", ""))[:10],
            "report_type": rt,
            "currency": r.get("CURRENCY", ""),
            "operate_income_yi": y("OPERATE_INCOME"),
            "holder_profit_yi": y("HOLDER_PROFIT"),
            "roe_avg_pct": r.get("ROE_AVG", ""),
            "gross_margin_pct": r.get("GROSS_PROFIT_RATIO", ""),
            "net_margin_pct": r.get("NET_PROFIT_RATIO", ""),
            "bps": r.get("BPS", ""),
            "basic_eps": r.get("BASIC_EPS", ""),
            "issued_shares": r.get("ISSUED_COMMON_SHARES", ""),
            "total_parent_equity_yi": y("TOTAL_PARENT_EQUITY"),
            "debt_asset_ratio_pct": r.get("DEBT_ASSET_RATIO", ""),
            "netcash_operate_yi": y("NETCASH_OPERATE"),
            "retrieved_at_utc": now,
            "source_url": f"{API}?reportName=RPT_HKF10_FN_MAININDICATOR&SECUCODE={code}.HK",
        })
    out.sort(key=lambda x: x["report_date"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="拉取港股逐年主要财务指标")
    ap.add_argument("--codes", required=True, help="逗号分隔的港股代码，如 01378")
    ap.add_argument("--out", type=Path,
                    default=Path("data/interim/hk_annual_financials.csv"))
    args = ap.parse_args()

    rows: list[dict] = []
    for code in [c.strip() for c in args.codes.split(",") if c.strip()]:
        got = fetch(code)
        print(f"{code}: 年报 {len(got)} 期"
              + (f"｜{got[0]['report_date'][:4]}~{got[-1]['report_date'][:4]}" if got else ""))
        rows.extend(got)

    if args.out.exists():
        with args.out.open(newline="", encoding="utf-8") as fh:
            old = [r for r in csv.DictReader(fh)
                   if (r["security_code"], r["report_date"]) not in
                   {(x["security_code"], x["report_date"]) for x in rows}]
        rows = old + rows
        rows.sort(key=lambda r: (r["security_code"], r["report_date"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

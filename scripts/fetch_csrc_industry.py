#!/usr/bin/env python3
"""证监会行业大类（东财 F10 公司概况 `INDUSTRYCSRC1`，另存东财行业 `EM2016`）→ `data/reference/a_share_csrc_industry.csv`。

OI-213 研发资本化按行业定摊销年限用；缺省取三大报表覆盖的全部代码。行业取现行分类，不回溯历史变动。

    python3 scripts/fetch_csrc_industry.py                 # 全部三大报表代码
    python3 scripts/fetch_csrc_industry.py --missing-only  # 只补表中缺行或未取到的三大报表代码（§6.7 第 1 步）
    python3 scripts/fetch_csrc_industry.py --codes 600276  # 指定代码（合并进现有表）
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/reference/a_share_csrc_industry.csv"
INCOME = ROOT / "data/raw/financials_statements/income.csv"
URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code={}"
FIELDS = ("security_code", "security_name", "csrc_industry", "em2016", "status", "retrieved_at_beijing")


def market_code(code: str) -> str:
    return ("SH" if code.startswith(("6", "9")) and not code.startswith("92") else
            "BJ" if code.startswith(("4", "8", "92")) else "SZ") + code


def fetch(code: str, retries: int = 2) -> dict:
    request = urllib.request.Request(URL.format(market_code(code)), headers={
        "Referer": "https://emweb.securities.eastmoney.com/", "User-Agent": "Mozilla/5.0"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
            if raw[:2] == b"\x1f\x8b":          # 服务器偶尔不经协商直接回 gzip
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            rows = data.get("jbzl") or []
            row = rows[0] if isinstance(rows, list) and rows else rows if isinstance(rows, dict) else {}
            if not row.get("INDUSTRYCSRC1"):
                return dict(status="no_industry", security_name=row.get("SECURITY_NAME_ABBR") or "")
            return dict(status="ok", security_name=row.get("SECURITY_NAME_ABBR") or "",
                        csrc_industry=row["INDUSTRYCSRC1"], em2016=row.get("EM2016") or "")
        except (OSError, ValueError) as exc:
            if attempt == retries:
                return dict(status=f"error:{type(exc).__name__}")
            time.sleep(2.0 * (attempt + 1))
    return dict(status="error")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--codes", help="逗号分隔代码；缺省取三大报表覆盖的全部代码")
    ap.add_argument("--missing-only", action="store_true", help="只取表中缺行或 status 非 ok 的代码")
    ap.add_argument("--pause", type=float, default=0.3, help="逐家请求间隔秒数")
    args = ap.parse_args()
    if args.codes:
        codes = sorted({c.strip().zfill(6) for c in args.codes.split(",") if c.strip()})
    else:
        with INCOME.open(encoding="utf-8-sig", newline="") as fh:
            codes = sorted({(r.get("SECURITY_CODE") or "").zfill(6) for r in csv.DictReader(fh)} - {"000000"})
    table = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8", newline="") as fh:
            table = {r["security_code"]: r for r in csv.DictReader(fh)}
    if args.missing_only:
        codes = [c for c in codes if table.get(c, {}).get("status") != "ok"]
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    for i, code in enumerate(codes, 1):
        row = dict(security_code=code, csrc_industry="", em2016="", retrieved_at_beijing=now) | fetch(code)
        table[code] = {k: row.get(k, "") for k in FIELDS}
        if i % 50 == 0:
            print(f"{i}/{len(codes)}", flush=True)
        time.sleep(args.pause)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(table[c] for c in sorted(table))
    bad = [c for c in codes if table[c]["status"] != "ok"]
    print(f"写入 {OUT}（{len(table)} 行）；本次 {len(codes)} 家，未取到 {len(bad)} 家：{','.join(bad[:20])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

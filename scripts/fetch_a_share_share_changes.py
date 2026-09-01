#!/usr/bin/env python3
"""股本变动事件取数（OI-126，用户 2026-09-01 指令建表）。

**为什么需要**：定期报告是「期末快照」，股本变动是「事件」——两者的时点不同，
而带的每股口径吃的是股本。判例：电投能源（002128）2026-06-03 为收购白音华煤电
增发 7.1183 亿股（22.4157→29.5340 亿），2026-07-17 配套定增再增 1.7308 亿股
（→31.2648 亿）；后一笔落在 2026 中报期末之后，**要到三季报才进定期报告**，
其间面板的每股口径整整滞后一个季度，而这段时间正是要拿 `P/V` 下买卖判断的时候。
把股本变动单独记成事件，就能在下一份定期报告到来之前知道口径已经变了。

同一控制下企业合并（CAS 20）还会把**比较期**一并追溯重述：电投能源 FY2025 的归母权益
已由 381.9982 亿重述为 471.7883 亿，而同一行的 `SHARE_CAPITAL` 仍是发行前的 22.4157 亿，
两者混基。本表记录的股本时点序列是判定这类混基的依据。

事件源：东财 F10 `RPT_F10_EH_EQUITY`（股本结构变动表），逐条给变动日、变动原因与
变动后的总股本／限售／流通股数。**只取数不判定**，消费方自行比对。

用法::

    python3 scripts/fetch_a_share_share_changes.py --signal-date 2026-09-01
    python3 scripts/fetch_a_share_share_changes.py --signal-date 2026-09-01 --codes 002128 600519
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUT = ROOT / "data/raw/share_changes/a_share_share_changes.csv"
API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
HEADERS = {"User-Agent": "Mozilla/5.0",
           "Referer": "https://emweb.securities.eastmoney.com/"}
FIELDS = ["security_code", "security_name", "effective_date", "change_reason",
          "total_shares", "limited_shares", "unlimited_shares", "shares_delta",
          "source", "retrieved_at_utc"]


def secucode(code: str) -> str:
    """六位代码 → 东财 `SECUCODE`（与 fetch_a_share_financial_statements 同式）。"""
    code = code.zfill(6)
    if code.startswith("92"):
        return f"{code}.BJ"
    if code[0] in "69":
        return f"{code}.SH"
    if code[0] in "03":
        return f"{code}.SZ"
    return f"{code}.BJ"


def num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_one(code: str, timeout: float) -> tuple[list[dict], str | None]:
    query = urllib.parse.urlencode({
        "reportName": "RPT_F10_EH_EQUITY", "columns": "ALL",
        "filter": f'(SECUCODE="{secucode(code)}")',
        "pageNumber": "1", "pageSize": "200",
        "sortTypes": "-1", "sortColumns": "END_DATE",
        "source": "HSF10", "client": "PC",
    })
    request = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return [], type(exc).__name__
    return ((payload.get("result") or {}).get("data") or []), None


def main() -> int:
    ap = argparse.ArgumentParser(description="股本变动事件取数")
    ap.add_argument("--signal-date", required=True, help="信号日 YYYY-MM-DD（只作留痕）")
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--codes", nargs="*", help="只取这些代码，缺省取核心池全体")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--pause", type=float, default=0.15)
    args = ap.parse_args()

    names: dict[str, str] = {}
    if args.codes:
        codes = [c.zfill(6) for c in args.codes]
    else:
        with args.pool.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        codes = [r["security_code"] for r in rows]
        names = {r["security_code"]: r["security_name"] for r in rows}

    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out_rows: list[dict] = []
    failures: list[str] = []
    print(f"股本变动事件取数：{len(codes)} 只｜信号日 {args.signal_date}")
    for index, code in enumerate(codes, start=1):
        data, error = fetch_one(code, args.timeout)
        if error:
            failures.append(f"{code}：{error}")
            time.sleep(args.pause)
            continue
        # 东财按 END_DATE 降序返回；升序遍历才能算出逐笔增量
        events = sorted(data, key=lambda r: (r.get("END_DATE") or ""))
        prev: float | None = None
        for row in events:
            total = num(row.get("TOTAL_SHARES"))
            delta = None if (total is None or prev is None) else total - prev
            out_rows.append({
                "security_code": code,
                "security_name": names.get(code, row.get("SECURITY_NAME_ABBR") or ""),
                "effective_date": (row.get("END_DATE") or "")[:10],
                "change_reason": (row.get("CHANGE_REASON") or "").strip(),
                "total_shares": f"{total:.0f}" if total is not None else "",
                "limited_shares": f"{num(row.get('LIMITED_SHARES')):.0f}"
                                  if num(row.get("LIMITED_SHARES")) is not None else "",
                "unlimited_shares": f"{num(row.get('UNLIMITED_SHARES')):.0f}"
                                    if num(row.get("UNLIMITED_SHARES")) is not None else "",
                "shares_delta": f"{delta:.0f}" if delta is not None else "",
                "source": "eastmoney:RPT_F10_EH_EQUITY",
                "retrieved_at_utc": stamp,
            })
            if total is not None:
                prev = total
        if index % 50 == 0:
            print(f"  {index}/{len(codes)}｜累计 {len(out_rows)} 条")
        time.sleep(args.pause)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_rows.sort(key=lambda r: (r["security_code"], r["effective_date"]))
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    covered = len({r["security_code"] for r in out_rows})
    print(f"wrote {len(out_rows)} share-change events for {covered}/{len(codes)} codes to {args.out}")
    if failures:
        print(f"  取数失败 {len(failures)} 只：{'；'.join(failures[:10])}"
              + ("…" if len(failures) > 10 else ""))
    return 0 if covered else 1


if __name__ == "__main__":
    raise SystemExit(main())

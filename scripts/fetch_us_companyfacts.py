#!/usr/bin/env python3
"""OI-159：按成员表下载 SEC companyfacts（`data/experiments/exp_us_sp500_port/raw/sec/CIK##########.json`，不入库）。

OI-150 已缓存的文件直接复制；其余按 SEC 公平使用节奏（≤ 10 请求/秒）下载。已有文件跳过（`--refresh` 强制重取）。
用法：python3 scripts/fetch_us_companyfacts.py [--members data/processed/us_sp500_members.csv] [--refresh] [--include-financial]
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/experiments/exp_us_sp500_port/raw/sec"
OI150 = ROOT / "data/experiments/exp_oi150_overseas_forward/raw/sec"
HDR = {"User-Agent": "RayKey research wzq9464@gmail.com", "Accept-Encoding": "identity"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--members", type=Path, default=ROOT / "data/processed/us_sp500_members.csv")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--include-financial", action="store_true")
    args = ap.parse_args()
    rows = list(csv.DictReader(args.members.open(encoding="utf-8")))
    ok_status = {"ok", "ok_sic_missing"} | ({"financial"} if args.include_financial else set())
    ciks = sorted({r["cik"] for r in rows if r["cik"] and r["status"] in ok_status})
    RAW.mkdir(parents=True, exist_ok=True)
    copied = fetched = skipped = failed = 0
    for i, cik in enumerate(ciks, 1):
        name = f"CIK{cik}.json"
        dst = RAW / name
        if dst.exists() and not args.refresh:
            skipped += 1; continue
        src = OI150 / name
        if src.exists() and not args.refresh:
            dst.write_bytes(src.read_bytes()); copied += 1; continue
        url = f"https://data.sec.gov/api/xbrl/companyfacts/{name}"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=90) as r:
                    dst.write_bytes(r.read())
                fetched += 1
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    print(f"  {cik} 失败：{exc}", file=sys.stderr); failed += 1
                time.sleep(3 * (attempt + 1))
        time.sleep(0.12)
        if i % 100 == 0:
            print(f"  {i}/{len(ciks)}", flush=True)
    print(f"companyfacts：{len(ciks)} 家，复制 {copied}、下载 {fetched}、已有 {skipped}、失败 {failed} → {RAW}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

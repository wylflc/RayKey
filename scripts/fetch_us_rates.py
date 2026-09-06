#!/usr/bin/env python3
"""OI-159：美债 10Y 日序列 → `data/reference/cost_of_equity_inputs_us.csv`（列同 A 股 `cost_of_equity_inputs.csv`）。

来源优先级：① 美国财政部逐年 CSV（OI-150 缓存 `data/experiments/exp_oi150_overseas_forward/raw/treasury/<年>.csv`，
当年文件早于 7 天则重取）；② FRED `DGS10`（财政部不可达时兜底）。rf = 收益率 ÷ 100；ERP 取
`data/reference/overseas_valuation_inputs.csv` 的 `erp_us` 常数。
用法：python3 scripts/fetch_us_rates.py [--since 2005-01-01] [--no-refresh]
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts/experimental"))
OUT = ROOT / "data/reference/cost_of_equity_inputs_us.csv"
INPUTS = ROOT / "data/reference/overseas_valuation_inputs.csv"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"


def from_treasury(since: str, refresh: bool) -> list[tuple[str, float]]:
    import overseas_pv_forward as opf
    year_now = date.today().year
    cur = opf.RAW / "treasury" / f"{year_now}.csv"
    if refresh and cur.exists() and (time.time() - cur.stat().st_mtime) > 7 * 86400:
        cur.unlink()                      # 当年文件过期即重取（load_rf 缺文件自动下载）
    dates, vals = opf.load_rf(range(int(since[:4]), year_now + 1))
    return [(d, v) for d, v in zip(dates, vals) if d >= since]


def from_fred(since: str) -> list[tuple[str, float]]:
    raw = ""
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(FRED_URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read().decode()
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  FRED 第 {attempt + 1} 次失败：{exc}", flush=True); time.sleep(20)
    if not raw:
        return []
    rows = list(csv.DictReader(raw.splitlines()))
    dcol = "observation_date" if "observation_date" in rows[0] else "DATE"
    return [(r[dcol], float(r["DGS10"]) / 100) for r in rows if r[dcol] >= since and r.get("DGS10", "").strip() not in ("", ".")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2005-01-01")
    ap.add_argument("--no-refresh", action="store_true")
    args = ap.parse_args()
    erp = next(float(r["value"]) for r in csv.DictReader(INPUTS.open(encoding="utf-8")) if r["key"] == "erp_us")
    series, source = from_treasury(args.since, not args.no_refresh), "US Treasury daily par yield curve 10Y (home.treasury.gov yearly CSV)"
    if not series:
        series, source = from_fred(args.since), "FRED DGS10"
    if not series:
        raise SystemExit("美债 10Y 取数失败（财政部与 FRED 都不可得）")
    today = date.today().isoformat()
    out = [{"observed_on": d, "risk_free_rate": f"{v:.6f}", "equity_risk_premium": f"{erp:.6f}",
            "source": f"{source} + damodaran erp_us (fetched {today})",
            "note": "R_f=美债10Y日频；ERP=Damodaran 美国 Total ERP 常数（overseas_valuation_inputs.csv erp_us）"} for d, v in series]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()), lineterminator="\n"); w.writeheader(); w.writerows(out)
    print(f"美债 10Y {len(out)} 行（{out[0]['observed_on']}～{out[-1]['observed_on']}，{source}）→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

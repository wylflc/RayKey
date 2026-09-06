#!/usr/bin/env python3
"""OI-159：美债 10Y 日序列（FRED `DGS10`）→ `data/reference/cost_of_equity_inputs_us.csv`（列同 A 股 `cost_of_equity_inputs.csv`）。

rf = DGS10 ÷ 100（年率）；ERP 取 `data/reference/overseas_valuation_inputs.csv` 的 `erp_us` 常数。
用法：python3 scripts/fetch_us_rates.py [--since 2005-01-01]
"""
from __future__ import annotations

import argparse
import csv
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/reference/cost_of_equity_inputs_us.csv"
INPUTS = ROOT / "data/reference/overseas_valuation_inputs.csv"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2005-01-01")
    args = ap.parse_args()
    erp = next(float(r["value"]) for r in csv.DictReader(INPUTS.open(encoding="utf-8")) if r["key"] == "erp_us")
    raw = ""
    for attempt in range(5):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read().decode()
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  FRED 第 {attempt + 1} 次失败：{exc}", flush=True)
            time.sleep(30 * (attempt + 1))
    if not raw:
        raise SystemExit("FRED DGS10 取数失败")
    rows = list(csv.DictReader(raw.splitlines()))
    dcol = "observation_date" if "observation_date" in rows[0] else "DATE"
    today = date.today().isoformat()
    out = []
    for r in rows:
        v = r.get("DGS10", "").strip()
        if r[dcol] < args.since or v in ("", "."):
            continue
        out.append({"observed_on": r[dcol], "risk_free_rate": f"{float(v) / 100:.6f}", "equity_risk_premium": f"{erp:.6f}",
                    "source": f"FRED DGS10 + damodaran erp_us (fetched {today})",
                    "note": "R_f=美债10Y日频（FRED DGS10）；ERP=Damodaran 美国 Total ERP 常数（overseas_valuation_inputs.csv erp_us）"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()), lineterminator="\n"); w.writeheader(); w.writerows(out)
    print(f"DGS10 {len(out)} 行（{out[0]['observed_on']}～{out[-1]['observed_on']}）→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""按成交日和成交价解析两侧估值，输出成交日志可用的 JSON。"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date

from a_share_signal_dates import evidence_iso_for_signal
from pv_ratio import load_model_bands, trading_pv
from screen_daily_volume_price_signals import (
    DEFAULT_HOLD_BANDS, DEFAULT_MODEL_BANDS, SECURITIES_MASTER, resolve_live_band,
)


def trade_valuation(code: str, name: str, as_of: str, price: float,
                    candidate_bands: dict, hold_bands: dict) -> dict:
    date.fromisoformat(as_of)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("成交价须为正有限数")
    result = {"as_of": as_of, "security_code": code.zfill(6),
              "security_name": name, "price": price}
    for side, bands in (("candidate", candidate_bands), ("hold", hold_bands)):
        band, source = resolve_live_band(code, name, as_of, bands)
        result[side] = {"intrinsic_value": band.get("intrinsic_value"),
                        "pv": trading_pv(price, band), "source": source}
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--price", required=True, type=float)
    args = ap.parse_args()
    code = args.code.zfill(6)
    name = args.name
    if not name:
        with SECURITIES_MASTER.open(encoding="utf-8-sig", newline="") as fh:
            name = next((r["security_name"] for r in csv.DictReader(fh)
                         if r["security_code"].zfill(6) == code), "")
    if not name:
        ap.error("证券名称不可得，请提供 --name")
    evidence = evidence_iso_for_signal(args.as_of)
    candidate = load_model_bands(DEFAULT_MODEL_BANDS, as_of=evidence)
    hold = load_model_bands(DEFAULT_HOLD_BANDS, as_of=evidence) if DEFAULT_HOLD_BANDS.exists() else candidate
    result = trade_valuation(code, name, args.as_of, args.price, candidate, hold)
    result["hold_fallback_to_candidate"] = not DEFAULT_HOLD_BANDS.exists()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(result[s]["pv"] is not None for s in ("candidate", "hold")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

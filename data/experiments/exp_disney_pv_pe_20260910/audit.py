#!/usr/bin/env python3
"""Reproduce the Disney P/V audit from frozen inputs; production files are read-only."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_overseas_roic_bands as bands


def main() -> None:
    snapshot = json.loads((HERE / "inputs.json").read_text())
    for name, expected in snapshot["input_sha256"].items():
        if name.startswith("scripts/"):
            actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError(f"Engine changed since audit; restore audited version: {name}")
    originals = snapshot["years"]
    corrected = copy.deepcopy(originals)
    annuals = [r for r in corrected if r["period_type"] == "annual"]
    annual_interest = abs(float(annuals[-1]["interest_expense"]))
    pair = snapshot["interest_ytd"]
    ttm_interest = annual_interest + abs(pair["current"]) - abs(pair["prior"])
    # Normalize the components before forming TTM. abs(final TTM) is incorrect
    # when annual and interim SEC facts use different expense sign conventions.
    assert ttm_interest == 1_795_000_000
    for row in corrected:
        interest = (ttm_interest if row["period_type"] == "ttm"
                    else abs(float(row["interest_expense"])))
        pretax, tax = float(row["pretax"]), float(row["income_tax"])
        rate = max(0.0, min(0.4, tax / pretax)) if pretax > 0 else 0.21
        row["interest_expense"] = interest
        row["ebit"] = pretax + interest
        row["nopat"] = row["ebit"] * (1 - rate)

    def evaluate(rows: list[dict]) -> dict:
        years = [bands.year_from_row(r) for r in rows if r["period_type"] == "annual"]
        current = bands.year_from_row(next(r for r in rows if r["period_type"] == "ttm"))
        value = bands.value_company("DIS", snapshot["tier"], years, snapshot["inputs"], current)
        assert value["status"] == "ok"
        ev = value["nopat_ps"] / value["wacc"]
        fin_debt = (current.interest_debt - current.excess_cash) / current.shares
        minority_book = current.minority_equity / current.shares
        minority_share = current.minority_equity / current.total_equity
        book_binds = minority_book >= minority_share * (ev - fin_debt)
        fixed_claim = fin_debt + (minority_book if book_binds else 0)
        hist = years[-5:]
        return {
            "model": value,
            "pv_at_frozen_price": snapshot["price"] / value["value"],
            "ev_ps": ev,
            "fin_net_debt_ps": fin_debt,
            "minority_book_ps": minority_book,
            "minority_book_binds": book_binds,
            "fixed_claim_ev_fraction": fixed_claim / ev,
            "would_reject_under_documented_thin_equity_rule": fixed_claim / ev >= 0.5,
            "ttm_interest": current.interest_expense,
            "ttm_ebit": current.ebit,
            "ttm_nopat": current.nopat,
            "annual_roic": {y.period: bands.roic_inputs.roic_of(y, hist[i-1] if i else None)
                            for i, y in enumerate(hist)},
        }

    original = evaluate(originals)
    assert math.isclose(original["model"]["value"], sum(snapshot["production_band"]) / 2,
                        abs_tol=0.005)
    fixed = evaluate(corrected)
    with patch.object(bands, "PEAK_RAMP", 0.0), patch.object(bands, "PEAK_K", 1e9):
        no_peak = evaluate(corrected)
    e = snapshot["earnings"]
    gaap = e["gaap_fy2025"] + e["gaap_9m2026"] - e["gaap_9m2025"]
    adjusted = e["adjusted_fy2025"] + e["adjusted_9m2026"] - e["adjusted_9m2025"]
    assert math.isclose(gaap, 4.85) and math.isclose(adjusted, 6.36)
    result = {
        "as_of": snapshot["as_of"], "price": snapshot["price"],
        "gaap_ttm_eps": gaap, "gaap_ttm_pe": snapshot["price"] / gaap,
        "adjusted_ttm_eps": adjusted, "adjusted_ttm_pe": snapshot["price"] / adjusted,
        "cases": {"production_reproduced": original, "interest_components_corrected": fixed,
                  "corrected_without_peak_normalization_diagnostic_only": no_peak},
        "checks": {"frozen_engine_hashes_match": True, "production_value_reproduced": True,
                   "mixed_sign_ttm_reconciles": True, "production_engine_and_bands_edited": False},
    }
    (HERE / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for label, case in result["cases"].items():
        print(f"{label}: V={case['model']['value']:.6f}, P/V={case['pv_at_frozen_price']:.6f}")
    print(f"GAAP EPS={gaap:.2f}, P/E={result['gaap_ttm_pe']:.4f}; "
          f"adjusted EPS={adjusted:.2f}, P/E={result['adjusted_ttm_pe']:.4f}")


if __name__ == "__main__":
    main()

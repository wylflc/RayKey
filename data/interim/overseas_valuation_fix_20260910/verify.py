#!/usr/bin/env python3
"""Reproduce the 2026-09-10 overseas rebuild audit against its frozen baseline."""
import csv
import hashlib
import io
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_overseas_roic_bands as bands
import build_a_share_core_valuation_pool as pool

BASELINE = "c25e3e77"
AS_OF = "2026-09-10"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(name, data):
    (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    before = {row["security_code"]: row for row in json.loads((HERE / "before.json").read_text())}
    rows = read_csv(bands.WATCHLIST)
    assert len(rows) == len(before) == len({r["security_code"] for r in rows}) == 29
    assert {r["security_code"] for r in rows} == set(before)
    inp, years = bands.load_inputs(), bands.load_years()
    current = bands.load_years.current
    results, comparison, counts = [], [], Counter()
    value_changes = []
    for row in rows:
        code = row["security_code"]
        old = before[code]
        for field in ("quality_tier", "quality_score", "attention_class", "currency"):
            assert row[field] == old[field], (code, field)
        model_value = trade_value = ratio = None
        if code in bands.FINANCIAL_KEEP:
            status = "keep"
            assert all(row[k] == old[k] for k in ("fair_price_low", "fair_price_high"))
        elif code in bands.NO_SOURCE:
            status = "unavailable"
        else:
            tier = row.get("quality_tier") or row.get("attention_class") or "L2"
            result = bands.value_company(code, tier, years[code], inp, current.get(code))
            results.append(dict(security_code=code, security_name=row["security_name"], result=result))
            status, model_value = result["status"], result.get("value")
            ratio = result.get("thin_equity_ratio")
            if model_value is not None:
                cfg = bands.COMPANY_CFG.get(code, dict(adr=1, fx=None))
                fx = inp[cfg["fx"]] if cfg.get("fx") else 1.0
                if cfg.get("fx_inv"):
                    fx = 1 / fx
                trade_value = model_value * fx * cfg["adr"]
                assert math.isfinite(trade_value) and trade_value > 0
                assert ratio < bands.THIN_EQUITY_MAX, (code, ratio)
                assert row["fair_price_low"] == f"{trade_value * bands.BAND_LOW_COEF:.2f}", code
                assert row["fair_price_high"] == f"{trade_value * bands.BAND_HIGH_COEF:.2f}", code
                if not math.isclose(model_value, old["model_value"], abs_tol=1e-8, rel_tol=1e-12):
                    value_changes.append(code)
            else:
                assert status == old["model_status"] == "rejected"
        counts[status] += 1
        midpoint = None
        if status in ("ok", "keep"):
            midpoint = (float(row["fair_price_low"]) + float(row["fair_price_high"])) / 2
            assert row["dossier_status"] == "active"
        else:
            assert row["fair_price_low"] == row["fair_price_high"] == ""
            assert row["band_derivation"] == "unvaluable"
            assert row["dossier_status"] == "unvaluable_pending_input"
        readme = ROOT / row["dossier_dir"] / "README.md"
        actual = readme.read_text()
        assert bands.render_readme(row, actual) == actual, code
        assert row["valuation_price"] and row["valuation_price_as_of"].replace("/", "-") == AS_OF, code
        old_midpoint = ((float(old["fair_price_low"]) + float(old["fair_price_high"])) / 2
                        if old["fair_price_low"] and old["fair_price_high"] else None)
        comparison.append(dict(security_code=code, security_name=row["security_name"], currency=row["currency"],
                               status=status, before_midpoint=old_midpoint, after_midpoint=midpoint,
                               before_model_report_ccy=old.get("model_value"), after_model_report_ccy=model_value,
                               after_model_trade_ccy=trade_value, fair_price_low=row["fair_price_low"],
                               fair_price_high=row["fair_price_high"], price=row["valuation_price"],
                               price_as_of=row["valuation_price_as_of"],
                               pv=float(row["valuation_price"]) / midpoint if midpoint else None,
                               thin_equity_ratio=ratio, evidence_date=row["valuation_reviewed_at"],
                               report_event=row["valuation_evidence_event"]))
    assert counts == {"ok": 22, "rejected": 2, "unavailable": 3, "keep": 2}
    assert set(value_changes) == {"ADBE", "DIS"}
    section = pool.build_overseas_section(rows, {})
    reading = (ROOT / "docs/000_a_share_core_valuation_pool.md").read_text()
    for row, compared in zip(rows, comparison):
        prefix = f"| {row['security_name']} |"
        expected = next(line for line in section if line.startswith(prefix))
        matches = [line for line in reading.splitlines() if line.startswith(prefix)]
        assert len(matches) == 1, row["security_code"]
        actual_cells = [c.strip() for c in matches[0].split("|")][1:-1]
        expected_cells = [c.strip() for c in expected.split("|")][1:-1]
        assert actual_cells[:6] + actual_cells[7:] == expected_cells[:6] + expected_cells[7:], row["security_code"]
        if not row["fair_price_low"]:
            assert actual_cells[5:7] == ["—", "—"]
        else:
            # The live view uses the quote's full precision; the stored quote has two decimals.
            assert abs(float(actual_cells[6]) - compared["pv"]) <= 0.001 + 0.005 / compared["after_midpoint"]
            compared["pv"] = float(actual_cells[6])
    old_bytes = subprocess.check_output(["git", "show", f"{BASELINE}:data/interim/overseas_roic_years.csv"], cwd=ROOT)
    old_statements = list(csv.DictReader(io.StringIO(old_bytes.decode())))
    new_statements = read_csv(bands.YEARS_CSV)
    key = lambda r: (r["security_code"], r["period"], r["period_type"])
    old_by_key, new_by_key = ({key(r): r for r in records} for records in (old_statements, new_statements))
    assert len(old_by_key) == len(new_by_key) == len(new_statements) == 444
    removed, added = sorted(old_by_key.keys() - new_by_key.keys()), sorted(new_by_key.keys() - old_by_key.keys())
    assert removed == [("ADBE", "2026-05-29", "ttm")]
    assert added == [("ADBE", "2026-08-28", "ttm")]
    metadata = {"source", "tags_used", "evidence_url", "report_label"}
    numeric_changes, metadata_changes = [], []
    for k in sorted(old_by_key.keys() & new_by_key.keys()):
        changed = {f: [old_by_key[k][f], new_by_key[k][f]] for f in old_by_key[k]
                   if old_by_key[k][f] != new_by_key[k][f]}
        values = {f: v for f, v in changed.items() if f not in metadata}
        if values:
            numeric_changes.append(dict(key=k, fields=values))
        if set(changed) & metadata:
            metadata_changes.append(dict(key=k, fields=sorted(set(changed) & metadata)))
    assert len(numeric_changes) == 10
    actual_dis = {r["period"]: float(r["interest_expense"]) for r in new_statements if r["security_code"] == "DIS"}
    for period, amount in {"2023-09-30": 1973e6, "2024-09-28": 2070e6, "2025-09-27": 1812e6, "2026-06-27": 1795e6}.items():
        assert actual_dis[period] == amount
    original_dis = [r for r in old_statements if r["security_code"] == "DIS"]
    rejected_dis = bands.value_company("DIS", "L2", [bands.year_from_row(r) for r in original_dis if r["period_type"] == "annual"],
                                       inp, bands.year_from_row(next(r for r in original_dis if r["period_type"] == "ttm")))
    assert rejected_dis["status"] == "rejected" and "薄权益" in rejected_dis["reason"]
    source = json.loads((HERE / "adobe_q3_source.json").read_text())
    adbe = new_by_key[added[0]]
    for name, (cur, prev) in source["income_ytd_millions_current_prior"].items():
        assert float(adbe[name]) == float(source["annual_base"][name]) + (cur - prev) * 1e6
    for name, (cur, prev) in source["cashflow_quarter_millions_current_prior"].items():
        assert float(adbe[name]) == float(source["prior_ttm_cashflow_base"][name]) + (cur - prev) * 1e6
    assert adbe["tci"] == "" and adbe["notice_date"] == AS_OF
    manifest = json.loads((HERE / "manifest.json").read_text())
    for name in ("data/processed/a_share_core_valuation_pool.csv", "data/reference/overseas_valuation_inputs.csv"):
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == manifest["before_sha256"][name], name
    write_json("model_results.json", results)
    write_json("statement_changes.json", dict(rows_before=444, rows_after=444, numeric_changes=numeric_changes,
               metadata_changes=metadata_changes, removed_rows=[old_by_key[k] for k in removed], added_rows=[new_by_key[k] for k in added]))
    with (HERE / "comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(comparison)
    verification = dict(as_of=AS_OF, baseline_commit=BASELINE, watchlist_companies=29, status_counts=dict(counts),
                        model_value_changed_codes=sorted(value_changes), readme_matches=29, reading_row_matches=29,
                        cleared_unvaluable_companies=5, quote_dates_match=29, classification_changes=0,
                        unchanged_a_share_pool=True, unchanged_valuation_parameters=True,
                        statement_rows_before=444, statement_rows_after=444, changed_common_statement_rows=len(numeric_changes),
                        metadata_changed_common_rows=len(metadata_changes), adobe_report_replacement=[removed[0], added[0]],
                        disney_original_inputs_guard=dict(status=rejected_dis["status"], path=rejected_dis["path"],
                                                          thin_equity_ratio=rejected_dis["thin_equity_ratio"]),
                        all_checks_passed=True)
    write_json("verification.json", verification)
    print(json.dumps(verification, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

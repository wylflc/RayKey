#!/usr/bin/env python3
"""Oracle official-statement overlays and research arithmetic; no price enters model inputs."""
import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_overseas_statements as source
import build_overseas_roic_bands as bands

Q1_URL = "https://investor.oracle.com/files/content_files/1q27-pressrelease-September_FINAL.pdf"
FY26_URL = "https://www.sec.gov/Archives/edgar/data/1341439/000119312526277521/orcl-20260531.htm"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001341439.json"


def main():
    payload = json.loads((ROOT / "data/raw/overseas_statements/sec/ORCL.json").read_text())
    tax = payload["facts"]["us-gaap"]
    raw_rows = source.sec_extract("ORCL", "甲骨文", payload)
    tags = {"LongTermNotesPayable": False, "DebtCurrent": False, "NotesPayableCurrent": False,
            "CommercialPaper": False, "FinanceLeaseLiabilityCurrent": False, "FinanceLeaseLiabilityNoncurrent": False,
            "Depreciation": True, "AmortizationOfIntangibleAssets": True,
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic": True,
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign": True}
    series = {tag: source._sec_series(tax, [tag], duration)[0] for tag, duration in tags.items()}
    overrides, corrected, reconciliation = [], [], []
    fields = next(csv.reader(source.STATEMENT_OVERRIDES.open()))
    for original in raw_rows:
        period = original["period"]
        long_notes = series["LongTermNotesPayable"].get(period)
        if long_notes is None:
            # FY2008 has no mapped balance sheet; retain the original gap outside the model window.
            continue
        row = {key: original.get(key) for key in fields}
        short_notes = series["DebtCurrent"].get(period)
        if short_notes is None:
            short_notes = series["NotesPayableCurrent"].get(period, 0) + series["CommercialPaper"].get(period, 0)
        finance_leases = sum(series[tag].get(period, 0) for tag in ("FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent"))
        domestic = series["IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"].get(period)
        foreign = series["IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign"].get(period)
        pretax = original["net_income"] + original["income_tax"]
        if domestic is not None and foreign is not None:
            if period >= "2023-05-31":
                assert abs(pretax - domestic - foreign) <= 1, period
            pretax = domestic + foreign
        row.update(pretax=pretax, interest_debt=long_notes + short_notes + finance_leases,
                   dep_amort=series["Depreciation"].get(period, 0) + series["AmortizationOfIntangibleAssets"].get(period, 0),
                   evidence_url=FACTS_URL,
                   source="Oracle SEC companyfacts reconciled: pretax=domestic+foreign (FY2023-26 also checked net income+tax); debt=noncurrent notes+current debt+disclosed finance leases; D&A=depreciation+intangible amortization")
        overrides.append(row)
        model_row = dict(original, **{k: row[k] for k in ("pretax", "interest_debt", "dep_amort")})
        model_row["ebit"] = pretax + original["interest_expense"]
        model_row["tax_rate"] = min(max(original["income_tax"] / pretax, 0), 0.4)
        model_row["nopat"] = model_row["ebit"] * (1 - model_row["tax_rate"])
        model_row["invested_capital"] = original["total_equity"] + row["interest_debt"] - original["excess_cash"]
        corrected.append(model_row)
        reconciliation.append(dict(period=period, original_pretax=original["pretax"], consolidated_pretax=pretax,
                                   original_debt=original["interest_debt"], notes_borrowings=long_notes + short_notes,
                                   finance_leases=finance_leases, corrected_debt=row["interest_debt"],
                                   original_da=original["dep_amort"], corrected_da=row["dep_amort"]))
    annual = overrides[-1]
    assert annual["period"] == "2026-05-31"
    assert annual["pretax"] == 19554e6 and annual["interest_debt"] == 137242e6
    assert annual["dep_amort"] == 9294e6
    # Q1 FY27 release, PDF pp. 5, 7 and 8; amounts in USD millions.
    pairs = dict(revenue=(19345, 14926), operating_income=(6728, 4277), pretax=(5607, 3427),
                 income_tax=(847, 500), interest_expense=(1428, 923), net_income=(4760, 2927),
                 cfo=(23103, 8140), capex=(28499, 8502), dep_amort=(3358, 1771),
                 buybacks=(0, 0), dividends_paid=(1484, 1413))
    quarter = {key: None for key in fields}
    quarter.update(market="US", security_code="ORCL", security_name="甲骨文", period="2026-08-31",
                   notice_date="2026-09-10", report_currency="USD", period_type="ttm",
                   report_label="一季报（FY2027Q1，官方业绩三表）", evidence_url=Q1_URL,
                   total_equity=67196e6, parent_equity=None, minority_equity=None,
                   interest_debt=(7625 + 117712) * 1e6, cash_like=(36369 + 708) * 1e6, shares=3000e6,
                   net_income_ytd=4760e6, dividends_paid_ytd=1484e6,
                   source="Oracle official Q1 FY27 release; annual+Q1_current-Q1_prior TTM; latest parent/minority equity and finance-lease breakdown not disclosed; debt contains disclosed notes/borrowings only; no ordinary-equity valuation until complete bridge")
    for key, (current, previous) in pairs.items():
        quarter[key] = annual[key] + (current - previous) * 1e6
    overrides.append(quarter)
    with (HERE / "official_overrides.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(overrides)
    diagnostic = bands.value_company("ORCL", "L2", [bands.year_from_row(row) for row in corrected], bands.load_inputs())
    price = json.loads((HERE / "quote.json").read_text())["US:ORCL"]["price"]
    eps = {"fy2026_gaap": 5.83, "q1_fy2026_gaap": 1.01, "q1_fy2027_gaap": 1.56,
           "fy2026_adjusted": 7.63, "fy2026_adjusted_ex_gains": 6.83, "q1_fy2026_adjusted": 1.47,
           "q1_fy2027_adjusted": 1.92, "fy2027_adjusted_guidance": 8.10}
    eps["ttm_gaap_quarter_sum"] = 5.83 - 1.01 + 1.56
    eps["ttm_adjusted_quarter_sum"] = 7.63 - 1.47 + 1.92
    eps["ttm_adjusted_ex_fy2026_gains"] = 6.83 - 1.47 + 1.92
    r, g = bands.load_inputs()["rf_usd"] + bands.load_inputs()["erp_us"], 0.03
    # Per-share FCFE after interest/preferred claims and dilution, not EPS or enterprise FCF.
    sensitivities = [dict(case=name, sustainable_next_year_fcfe_per_share=fcfe,
                         value_if_steady_now=fcfe / (r - g), value_if_five_zero_cash_years=fcfe / (r - g) / (1 + r)**5)
                     for name, fcfe in (("bear", 6.0), ("base", 9.0), ("bull", 12.0))]
    facts = dict(as_of="2026-09-10", quarter_period="2026-08-31", sources=dict(q1=Q1_URL, fy2026=FY26_URL, companyfacts=FACTS_URL),
                 q1_current_prior_millions=pairs, q1_cashflow_millions=dict(cfo=23103, capex=28499, fcf=-5396,
                 financing_component_customer_prepayments=11363, cfo_ex_these_prepayments=11740,
                 fcf_ex_these_prepayments=-16759, capex_net_cash_outlay=17966, atm_common_issuance_gross=20000),
                 q1_balance_millions=dict(cash=36369, securities=708, notes_current=7625, notes_noncurrent=117712,
                 reported_total_equity=67196, parent_equity=None, minority_equity=None),
                 q1_rpo_billions=664, q1_oci_revenue_billions=7.4, q1_oci_growth=1.21,
                 annual_lease_liability_millions=dict(operating=30190, finance=7701),
                 annual_preferred_stock_millions=4954, annual_preferred_conversion_date="2029-01-15",
                 fy2026_rpo_recognition_windows=dict(next_12_months=0.12, months_13_to_36=0.34, months_37_to_60=0.34, thereafter=0.20),
                 ttm_cfo=quarter["cfo"], ttm_capex=quarter["capex"], ttm_fcf=quarter["cfo"]-quarter["capex"],
                 eps=eps, price=price, pe={key:price / eps[key] for key in ("ttm_gaap_quarter_sum", "ttm_adjusted_quarter_sum", "ttm_adjusted_ex_fy2026_gains", "fy2027_adjusted_guidance")},
                 cash_sensitivity=dict(required_return=r, terminal_growth=g, scenarios=sensitivities,
                 required_steady_next_year_fcfe_per_share=price*(r-g),
                 required_year6_fcfe_if_five_zero_cash_years=price*(r-g)*(1+r)**5,
                 assumptions="Illustrative FCFE sensitivity, not a forecast or production band. Includes interest, maintenance/reinvestment, preferred claims and dilution; no second net-debt deduction. Delayed case sets years 1-5 cash to zero; actual negative cash/financing would reduce value further."),
                 gaps=["Latest Q1 parent/minority equity not separated in release", "Latest finance leases and mandatory convertible preferred bridge require filed Q1 10-Q", "No current TTM comprehensive income in release"],
                 annual_reconciliation=reconciliation,
                 raw_sha256=hashlib.sha256((ROOT / "data/raw/overseas_statements/sec/ORCL.json").read_bytes()).hexdigest())
    for name, data in (("official_inputs.json", facts), ("annual_model_diagnostic.json", dict(warning="FY2026 annual-only diagnostic, not current valuation; incomplete preferred-stock bridge", result=diagnostic))):
        (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(overlay_rows=len(overrides), ttm_fcf=facts["ttm_fcf"], pe=facts["pe"],
                         sensitivity=facts["cash_sensitivity"], annual_diagnostic_value=diagnostic.get("value")),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()

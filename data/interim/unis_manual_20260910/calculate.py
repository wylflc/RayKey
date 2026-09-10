"""Single-company, user-requested scenario arithmetic; never a production input.

Run: python3 data/interim/unis_manual_20260910/calculate.py
All amounts are CNY 100 million; shares are 100 million; per-share values are CNY.
Facts, assumptions, sources and limitations: company manual_valuation_20260910.md.
"""

import json
from pathlib import Path


FACTS = {
    "information_cutoff": "2026-09-10 Asia/Shanghai",
    "balance_sheet_date": "2026-06-30",
    "shares": 28.60079874,
    "cash": 71.3659640524,
    "short_debt": 144.4246164483,
    "current_noncurrent_debt": 39.6033154184,
    "long_debt": 99.9252831853,
    "lease_debt": 7.0954154443,
    "put_pv": 44.46099542,
    "dividend_pv_all_h3c_minority": 7.9178008562,
    "h3c_minority": 0.1202,
    "put_covered": 0.1006,
    "minority_book_group": 20.0175881091,
    "minority_book_h3c": 13.8447427448,
    "h3c_np_fy2025": 31.5148896387,
    "h3c_np_h1_2026": 23.8809062502,
    "h3c_np_h1_2025": 18.5084954215,
    "h3c_appraisal_after_historical_dividends": 515.999132,
    "placement_proceeds_cap": 54.10,
    "placement_shares_cap": 4.30,
}

H1_OPERATING = {
    "revenue": 635.1582406948,
    "cost": -550.0108534897,
    "tax_surcharges": -1.8485676377,
    "selling": -21.4192463564,
    "admin": -5.0078777620,
    "research": -24.6908744742,
    "other_income": 4.1863157758,
    "remove_nonrecurring_grants": -0.8982505360,
    "credit_impairment": -0.7750903741,
    "asset_impairment": -6.7553991216,
    "remove_individual_receivable_reversal": -0.1924324408,
}

SCENARIOS = {
    "bear": {"nopat0": 40, "g0": 0.05, "incremental_roic0": 0.10,
             "wacc": 0.08, "h3c_pe": 14},
    "base": {"nopat0": 45, "g0": 0.08, "incremental_roic0": 0.12,
             "wacc": 0.075, "h3c_pe": 18},
    "bull": {"nopat0": 50, "g0": 0.12, "incremental_roic0": 0.14,
             "wacc": 0.07, "h3c_pe": 22},
}


def enterprise_value(s):
    """Ten yearly FCFFs, with both growth and incremental return fading."""
    n, r, gt = s["nopat0"], s["wacc"], 0.03
    rt = min(s["incremental_roic0"], r + 0.02)
    years = []
    for t in range(1, 11):
        fade = (t - 1) / 9
        g = s["g0"] + (gt - s["g0"]) * fade
        ri = s["incremental_roic0"] + (rt - s["incremental_roic0"]) * fade
        n *= 1 + g
        reinvestment = n * g / ri
        fcff = n - reinvestment
        years.append({"year": t, "g": g, "roic": ri, "nopat": n,
                      "reinvestment": reinvestment, "fcff": fcff,
                      "pv": fcff / (1 + r) ** t})
    terminal_pv = n * (1 + gt) * (1 - gt / rt) / (r - gt) / (1 + r) ** 10
    ev = sum(y["pv"] for y in years) + terminal_pv
    return ev, terminal_pv, years


def bridge(ev, h, *, alpha=0.8, surplus_cash=0, put_multiplier=1,
           dividend_multiplier=1, other_minority_multiplier=1, swap_all=False):
    """PV-equivalent exit scenarios; alpha is an assumption, not a contract fact.

    alpha = issue price / post-deal fair share value, in equivalent PV units.
    A share issue worth C at alpha * fair value transfers C / alpha to recipients.
    No independent dilution is subtracted again. See report for timing assumptions.
    """
    f = FACTS
    debt = sum(f[k] for k in ("short_debt", "current_noncurrent_debt",
                              "long_debt", "lease_debt"))
    other = (f["minority_book_group"] - f["minority_book_h3c"]) * other_minority_multiplier
    q_total = ev - debt + surplus_cash - other
    s, p = f["h3c_minority"], f["put_covered"]
    q = s - p
    div = f["dividend_pv_all_h3c_minority"] * dividend_multiplier
    # Same dividends per H3C share, an explicit research allocation assumption.
    div_p, div_q = div * p / s, div * q / s
    ordinary_q = max(q * h, div_q)
    k = f["put_pv"] * put_multiplier
    cash_equity = q_total - ordinary_q - k - div_p
    swap_p = s if swap_all else p
    swap_div = div if swap_all else div_p
    swap_ordinary = 0 if swap_all else ordinary_q
    # H includes interim dividends; remove them before pricing remaining shares.
    swap_consideration_pv = swap_p * h - swap_div
    assert swap_consideration_pv >= 0
    pre_issue_equity = q_total - swap_ordinary - swap_div
    swap_equity = pre_issue_equity - swap_consideration_pv / alpha
    stock_iv = swap_equity / f["shares"]
    equivalent_issue_price = alpha * stock_iv
    new_shares = swap_consideration_pv / equivalent_issue_price
    assert abs(pre_issue_equity / (f["shares"] + new_shares) - stock_iv) < 1e-9
    return {"ev": ev, "h3c_equity": h, "financial_debt": debt,
            "surplus_cash": surplus_cash, "other_minority": other,
            "Q": q_total, "put_pv": k, "dividend_pv_covered": div_p,
            "dividend_pv_ordinary": div_q, "ordinary_h3c_minority": ordinary_q,
            "swap_alpha": alpha, "swap_consideration_pv": swap_consideration_pv,
            "swap_equity_transfer": swap_consideration_pv / alpha,
            "cash_equity": cash_equity, "swap_equity": swap_equity,
            "cash_iv": cash_equity / f["shares"], "swap_iv": stock_iv,
            "equivalent_swap_new_shares": new_shares,
            "equivalent_swap_issue_price": equivalent_issue_price}


def calculate():
    f = FACTS
    h3c_ttm = f["h3c_np_fy2025"] + f["h3c_np_h1_2026"] - f["h3c_np_h1_2025"]
    result = {"purpose": "research_only_not_production", "facts": f,
              "h1_operating_components": H1_OPERATING,
              "h1_operating_ebit": sum(H1_OPERATING.values()),
              "h1_annualized_nopat_at_15pct_tax": sum(H1_OPERATING.values()) * 2 * 0.85,
              "h3c_ttm_np": h3c_ttm, "scenarios": {}}
    for name, s in SCENARIOS.items():
        ev, tv, years = enterprise_value(s)
        h = h3c_ttm * s["h3c_pe"]
        b = bridge(ev, h)
        b.update({"assumptions": s, "terminal_share": tv / ev,
                  "terminal_pv": tv, "years": years})
        # Mechanical immediate-equivalent placement, full cash credited once.
        b["placement_full_cap_cash_iv"] = (b["cash_equity"] + 54.10) / (f["shares"] + 4.30)
        b["placement_full_cap_swap_iv"] = (b["swap_equity"] + 54.10) / (f["shares"] + 4.30)
        result["scenarios"][name] = b
    base = result["scenarios"]["base"]
    ev, h = base["ev"], base["h3c_equity"]
    sensitivity = {}
    for label, changes in {
        "alpha_0.6": {"alpha": 0.6}, "alpha_1.0": {"alpha": 1.0},
        "surplus_cash_25": {"surplus_cash": 25},
        "surplus_cash_50": {"surplus_cash": 50},
        "put_plus_10pct": {"put_multiplier": 1.1},
        "dividends_plus_20pct": {"dividend_multiplier": 1.2},
        "other_minority_double_book": {"other_minority_multiplier": 2},
        "all_12.02pct_swap": {"swap_all": True},
    }.items():
        z = bridge(ev, h, **changes)
        sensitivity[label] = {k: z[k] for k in ("cash_iv", "swap_iv")}
    for label, h_value in {
        "h3c_appraisal_anchor": f["h3c_appraisal_after_historical_dividends"],
        "h3c_value_minus_30pct": h * 0.7,
        "h3c_value_plus_30pct": h * 1.3,
    }.items():
        z = bridge(ev, h_value)
        sensitivity[label] = {k: z[k] for k in ("cash_iv", "swap_iv")}
    for r in (0.065, 0.07, 0.08, 0.085, 0.10):
        s = dict(SCENARIOS["base"], wacc=r)
        ev_r, _, _ = enterprise_value(s)
        z = bridge(ev_r, h)
        sensitivity[f"wacc_{r}"] = {"ev": ev_r, "cash_iv": z["cash_iv"], "swap_iv": z["swap_iv"]}
    result["base_sensitivities"] = sensitivity
    # Economic identities: fair-price swap equals ordinary minority ownership;
    # reallocating dividends does not create an extra claim in that case.
    fair = bridge(ev, h, alpha=1)
    fair_more_div = bridge(ev, h, alpha=1, dividend_multiplier=1.2)
    ordinary = (fair["Q"] - f["h3c_minority"] * h) / f["shares"]
    assert abs(fair["swap_iv"] - ordinary) < 1e-9
    assert abs(fair_more_div["swap_iv"] - ordinary) < 1e-9
    assert abs(sensitivity["surplus_cash_25"]["cash_iv"] - base["cash_iv"] - 25 / f["shares"]) < 1e-9
    result["checks"] = {"share_issue_identity": "passed_in_every_bridge",
                        "fair_price_swap_equals_ordinary_equity": "passed",
                        "no_double_counted_dividend_at_fair_price": "passed",
                        "cash_credit_per_share_identity": "passed"}
    return result


if __name__ == "__main__":
    output = calculate()
    path = Path(__file__).with_name("results.json")
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"h1_annualized_nopat": output["h1_annualized_nopat_at_15pct_tax"],
                      "scenarios": {k: {x: v[x] for x in ("ev", "h3c_equity", "cash_iv", "swap_iv", "terminal_share", "placement_full_cap_cash_iv", "placement_full_cap_swap_iv")}
                                    for k, v in output["scenarios"].items()},
                      "sensitivities": output["base_sensitivities"],
                      "checks": output["checks"]}, ensure_ascii=False, indent=2))

"""OI-216: gaps vs pipeline and V effects by re-running the repo engine (read-only; run with python3 -B).

Reads data/interim/overseas_roic_years.csv and data/processed/overseas_watchlist_valuation.csv from the repo,
applies the corrections from oi216_data.py to copies of the rows, and calls build_overseas_roic_bands.value_company.
Nothing is written inside the repository.
"""
from __future__ import annotations

import copy
import csv
import json
import sys
from pathlib import Path

REPO = Path("/gpfs/scratch1/shared/zwang/mm_quant/RayKey")
OUT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_overseas_roic_bands as B  # noqa: E402
import roic_inputs  # noqa: E402
import oi216_data as D  # noqa: E402

ROWS = list(csv.DictReader((REPO / "data/interim/overseas_roic_years.csv").open(encoding="utf-8")))
WATCH = {r["security_code"]: r for r in csv.DictReader((REPO / "data/processed/overseas_watchlist_valuation.csv").open(encoding="utf-8-sig"))}
INP = B.load_inputs()
IC_FLOOR = 0.1  # fetch_overseas_statements.IC_FLOOR (§6.5.1 invested-capital floor)


def f(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def rows_of(code):
    return [dict(r) for r in ROWS if r["security_code"] == code]


def key(r):
    return (r["period"], r["period_type"])


def recompute(r, d_ebit=0.0, d_cash=0.0, other_new=None, d_other=0.0, d_debt=0.0, te_new=None, pe_new=None, minority_new=None):
    """Apply deltas and recompute nopat / excess cash / invested capital with the _build_row formulas."""
    if d_ebit:
        r["ebit"] = str(f(r["ebit"]) + d_ebit)
        rate = f(r["tax_rate"])
        r["nopat"] = str(f(r["ebit"]) * (1 - rate))
    cash = (f(r["cash_like"]) or 0.0) + d_cash
    other = (f(r["other_financial_assets"]) or 0.0) if other_new is None else other_new
    other += d_other
    r["cash_like"], r["other_financial_assets"] = str(cash), str(other)
    if te_new is not None:
        r["total_equity"] = str(te_new)
    if pe_new is not None:
        r["parent_equity"] = str(pe_new)
    if minority_new is not None:
        r["minority_equity"] = str(minority_new)
    rev = f(r["revenue"]) or 0.0
    excess = max(0.0, cash - roic_inputs.OPERATING_CASH_RATIO * rev) + max(0.0, other)
    r["excess_cash"] = str(excess)
    debt = (f(r["interest_debt"]) or 0.0) + d_debt
    r["interest_debt"] = str(debt)
    te = f(r["total_equity"])
    if te is not None:
        ic = max(debt + te - excess, IC_FLOOR * te)
        r["invested_capital"] = str(ic) if ic > 0 else ""
    return r


def value(code, rows):
    ann = sorted((B.year_from_row(r) for r in rows if r["period_type"] == "annual"), key=lambda y: y.period)
    ttm = [B.year_from_row(r) for r in rows if r["period_type"] == "ttm"]
    cur = ttm[-1] if ttm else None
    res = B.value_company(code, "", ann, INP, cur)
    cfg = B.COMPANY_CFG.get(code, dict(ccy="USD", adr=1, fx=None, fx_inv=False))
    fx = 1.0
    if cfg.get("fx"):
        fx = INP[cfg["fx"]]
        fx = (1.0 / fx) if cfg.get("fx_inv") else fx
    v = res.get("value")
    vt = v * fx * cfg["adr"] if v is not None and res["status"] == "ok" else None
    return res, vt


def summarize(code, label, res, vt, price):
    keys = ("value", "path", "mode", "ratio0", "roic0", "g0", "nopat_ps", "net_debt_ps", "bps_op", "peak_w", "trough_w")
    out = {k: res.get(k) for k in keys}
    out.update(status=res["status"], reason=res.get("reason", ""), v_trade=vt, pv=(price / vt if vt and price else None),
               ratios=[round(x, 4) for x in res.get("ratios", [])])
    return {"code": code, "scenario": label, **out}


RESULTS = []
FINDINGS = []


def finding(company, period, item, value, currency, source, current, gap, fix):
    FINDINGS.append(dict(company=company, period=period, item=item,
                         value=None if value is None else round(value, 3), currency=currency, source=source,
                         current_pipeline_value=None if current is None else round(current, 3),
                         gap=None if gap is None else round(gap, 3), proposed_fix=fix))


def run(code, scenarios):
    price = f(WATCH[code]["valuation_price"])
    base = rows_of(code)
    res, vt = value(code, base)
    RESULTS.append(summarize(code, "baseline (repo rows as-is)", res, vt, price))
    for label, fn in scenarios:
        rows = fn(copy.deepcopy(base))
        res, vt = value(code, rows)
        RESULTS.append(summarize(code, label, res, vt, price))


# ================================================================== 00316 OOIL
def f10_income(code):
    d = json.load((REPO / f"data/raw/overseas_statements/hk/{code}_income.json").open(encoding="utf-8"))
    per = {}
    for r in d:
        per.setdefault(str(r["REPORT_DATE"])[:10], {})[r["STD_ITEM_NAME"]] = f(r["AMOUNT"])
    return per


OOIL_F10 = f10_income("00316")


def ooil_cny(period):
    src, rev, ooi, op, b, fs, ac, fvtpl_i, distr, div, fvoci = D.OOIL[period]
    fx = OOIL_F10[period]["营业额"] / (rev * 1e3)
    interest = (b + fs + ac + fvtpl_i) * 1e3
    portfolio = ((distr or 0) + (div or 0) + (fvoci or 0)) * 1e3
    return fx, interest, portfolio


def ooil_findings():
    for p in sorted(D.OOIL):
        src, rev, ooi, op, b, fs, ac, fvtpl_i, distr, div, fvoci = D.OOIL[p]
        fx, interest, portfolio = ooil_cny(p)
        url, ref = D.OOIL_SRC[src]
        f10_oi = OOIL_F10[p]["其他收入"]
        ptype = "annual" if p.endswith("12-31") else "interim_ytd"
        finding("00316 东方海外国际", f"{p} ({ptype})", "interest income inside Other operating income (banks + fellow-subsidiary deposits + amortised-cost investments + FVTPL portfolio interest); inside Operating profit",
                interest / 1e3, "USD thousand", f"{url} | {ref}", 0.0, interest / 1e3,
                f"subtract from EBIT; CNY at F10 FX {fx:.4f} = {interest*fx/1e9:.4f} bn (F10 其他收入 {f10_oi/1e9:.4f} bn = OOI {ooi:,} kUSD x FX)")
        finding("00316 东方海外国际", f"{p} ({ptype})", "portfolio investment income inside Other operating income (FVTPL distribution + dividends, FVOCI dividends)",
                portfolio / 1e3, "USD thousand", f"{url} | {ref}", 0.0, portfolio / 1e3,
                f"optional (immaterial): subtract with interest; CNY {portfolio*fx/1e9:.4f} bn")
    # TTM
    fxa, ia, _ = ooil_cny("2025-12-31"); fxc, ic, _ = ooil_cny("2026-06-30"); fxp, ip, _ = ooil_cny("2025-06-30")
    ttm = ia * fxa + ic * fxc - ip * fxp
    finding("00316 东方海外国际", "2026-06-30 (ttm)", "interest income inside Operating profit, TTM = FY2025 + 1H26 - 1H25 (each at F10 FX)",
            ttm / 1e9, "CNY bn", "derived from AR2025 note 7 + IR2026 note 7", 0.0, ttm / 1e9,
            "subtract from TTM EBIT (hk_current_extract ttm of the supplement)")
    return ttm


def ooil_scen(rows):
    for r in rows:
        p, t = key(r)
        if t == "annual" and p in D.OOIL:
            fx, i, _ = ooil_cny(p)
            recompute(r, d_ebit=-i * fx)
        elif t == "ttm" and p == "2026-06-30":
            fxa, ia, _ = ooil_cny("2025-12-31"); fxc, ic, _ = ooil_cny("2026-06-30"); fxp, ip, _ = ooil_cny("2025-06-30")
            recompute(r, d_ebit=-(ia * fxa + ic * fxc - ip * fxp))
    return rows


# ================================================================== 06862 Haidilao
def hdl_fin(p):
    src, tot, bank, ofa, fvoci, rental = D.HDL[p]
    return (bank + ofa + fvoci) * 1e3, rental * 1e3


def hdl_findings():
    for p in sorted(D.HDL):
        src, tot, bank, ofa, fvoci, rental = D.HDL[p]
        url, ref = D.HDL_SRC[src]
        fin, rent = hdl_fin(p)
        ptype = "annual" if p.endswith("12-31") else "interim_ytd"
        finding("06862 海底捞", f"{p} ({ptype})", "interest income inside Other income on bank deposits + other financial assets + FVTOCI/FVTPL (inside F10 经营溢利)",
                fin / 1e3, "RMB thousand", f"{url} | {ref}", 0.0, fin / 1e3,
                f"subtract from EBIT ({fin/1e9:.4f} bn); other income total {tot:,}k = F10 其他收入")
        finding("06862 海底捞", f"{p} ({ptype})", "interest income on rental deposits (unwinding on operating lease deposits)",
                rent / 1e3, "RMB thousand", f"{url} | {ref}", 0.0, None, "keep in EBIT (rental deposits are operating assets, not in excess cash)")
    ttm = hdl_fin("2025-12-31")[0] + hdl_fin("2026-06-30")[0] - hdl_fin("2025-06-30")[0]
    finding("06862 海底捞", "2026-06-30 (ttm)", "financial interest income inside Other income, TTM = FY2025 + 1H26 - 1H25",
            ttm / 1e9, "RMB bn", "derived from AR2025 note 6 + IR2026 note 4", 0.0, ttm / 1e9, "subtract from TTM EBIT")
    return ttm


def hdl_scen(rows):
    for r in rows:
        p, t = key(r)
        if t == "annual" and p in D.HDL:
            recompute(r, d_ebit=-hdl_fin(p)[0])
        elif t == "ttm" and p == "2026-06-30":
            recompute(r, d_ebit=-(hdl_fin("2025-12-31")[0] + hdl_fin("2026-06-30")[0] - hdl_fin("2025-06-30")[0]))
    return rows


# ================================================================== 09618 JD
def jd_em(p):
    return D.JD_EM[p][1] * 1e6


def jd_other(p, carry_nonem=None):
    src, eq_inv, em, msoi = D.JD_BS[p]
    nonem = (eq_inv - em) if em is not None else carry_nonem
    return (msoi + (nonem or 0)) * 1e6, nonem


def jd_findings():
    rows = {key(r): r for r in rows_of("09618")}
    for p in sorted(D.JD_EM):
        src, em, ii, on = D.JD_EM[p]
        url, ref = D.JD_SRC[src]
        t = "annual" if p.endswith("12-31") else "interim_ytd"
        has_row = (p, "annual") in rows
        cur = f(rows[(p, "annual")].get("equity_method_income")) if has_row else None
        fix = "add to EBIT (equity-method income stays in EBIT, §6.8)"
        if t != "annual":
            fix += "; interim YTD input for the TTM row"
        elif not has_row:
            fix = "no pipeline row (F10 history starts 2017); reference only"
        finding("09618 京东集团", f"{p} ({t})", "share of results of equity investees (below Income from operations; F10 merges it into 溢利其他项目)",
                em, "RMB million", f"{url} | {ref}", None if cur is None else cur / 1e6, (em - (cur or 0) / 1e6) if has_row else None, fix)
        if ii is not None:
            finding("09618 京东集团", f"{p} ({t})", "interest income inside 'Others, net' (below operating income)", ii, "RMB million",
                    f"{url} | {ref}", None, None, f"no EBIT change (already outside EBIT); Others,net total {on:,}; F10 溢利其他项目 = equity-method share + Others,net")
    ttm = jd_em("2025-12-31") + jd_em("2026-06-30") - jd_em("2025-06-30")
    finding("09618 京东集团", "2026-06-30 (ttm)", "share of results of equity investees TTM = FY2025 + 1H26 - 1H25", ttm / 1e6, "RMB million",
            "derived AR2025 + IA2026", 0.0, ttm / 1e6, "add to TTM EBIT")
    carry = None
    for p in sorted(D.JD_BS):
        src, eq_inv, em, msoi = D.JD_BS[p]
        url, ref = D.JD_SRC[src]
        t = "annual" if p.endswith("12-31") else "ttm"
        val, nonem = jd_other(p, carry)
        if em is not None:
            carry = nonem
        cur = f(rows.get((p, t), {}).get("other_financial_assets"))
        note = ("equity-method part of 'Investments in equity investees' stays in IC; non-equity-method part (measurement alternative + NAV funds) "
                "+ 'Marketable securities and other investments' (listed equity, LT time deposits, LT wealth management) = other financial assets")
        if em is None:
            note += f"; 1H26 equity-method split not disclosed: non-EM part carried from FY2025 ({carry:,} m) - ESTIMATE"
        finding("09618 京东集团", f"{p} ({t})", f"non-current financial assets: equity investees {eq_inv:,} (of which equity method {em if em is not None else 'n/a'}), marketable securities & other investments {msoi:,}",
                val / 1e6, "RMB million", f"{url} | {ref}", None if cur is None else cur / 1e6, None if cur is None else (val - cur) / 1e6,
                "supplement other_financial_assets; " + note)


def jd_scen(em=True, bs=False, fill2023=False):
    def fn(rows):
        carry = None
        nonem_by = {}
        for p in sorted(D.JD_BS):
            v, nonem = jd_other(p, carry)
            if D.JD_BS[p][2] is not None:
                carry = nonem
            nonem_by[p] = v
        for r in rows:
            p, t = key(r)
            d_ebit = 0.0
            if em:
                if t == "annual" and p in D.JD_EM:
                    d_ebit = jd_em(p)
                elif t == "ttm" and p == "2026-06-30":
                    d_ebit = jd_em("2025-12-31") + jd_em("2026-06-30") - jd_em("2025-06-30")
            other_new = nonem_by.get(p) if bs and p in nonem_by else None
            kw = {}
            if fill2023 and t == "annual" and p == "2023-12-31":
                z = D.JD_2023_FILL
                kw = dict(d_cash=(z["cash"] + z["st_invest"]) * 1e6, te_new=z["total_equity"] * 1e6, pe_new=z["parent_equity"] * 1e6)
            recompute(r, d_ebit=d_ebit, other_new=other_new, **kw)
        return rows
    return fn


# ================================================================== NVDA / UBER / META
def nvda_findings():
    rows = {key(r): r for r in rows_of("NVDA")}
    for p, v in D.NVDA_EQ_CURRENT.items():
        t = "annual" if p == "2026-01-25" else "ttm"
        cur = f(rows[(p, t)]["cash_like"])
        src = D.SEC_SRC["NVDA_10Q_Q2FY27"] + " (R4 balance sheet: us-gaap:EquitySecuritiesFvNi 'Marketable equity securities', both columns)"
        if p == "2026-01-25":
            src += "; 10-K FY26 R5 face line nvda:MarketableSecuritiesAndEquitySecuritiesFVNI 51,951 = DebtSecuritiesCurrent 39,065 + EquitySecuritiesFvNi 12,886"
        finding("NVDA 英伟达", f"{p} ({t})", "current marketable equity securities (publicly-held; us-gaap:EquitySecuritiesFvNi, present in companyfacts)",
                v, "USD million", src, 0.0, v,
                f"cash-like (current). Pipeline cash_like {cur/1e6:,.0f} = cash + DebtSecuritiesCurrent only; tag-group fix: composite candidate DebtSecuritiesCurrent+EquitySecuritiesFvNi in US_SECURITIES_CURRENT (see summary)")
    p = "2026-07-26"
    finding("NVDA 英伟达", f"{p} (ttm)", "equity-method securities inside face 'Non-marketable securities' (nvda:NonMarketableSecurities 51,157 - measurement alternative 47,898)",
            D.NVDA_EQUITY_METHOD_IN_NONMKT[p], "USD million", D.SEC_SRC["NVDA_10Q_Q2FY27_R43"] + " ('Equity method securities 3,300')",
            None, None, "no change: equity-method stays in IC; pipeline other 47,898 = EquitySecuritiesWithoutReadilyDeterminableFairValueAmount is correct")


def nvda_scen(rows):
    for r in rows:
        p, t = key(r)
        if p in D.NVDA_EQ_CURRENT:
            recompute(r, d_cash=D.NVDA_EQ_CURRENT[p] * 1e6)
    return rows


def uber_findings():
    rows = {key(r): r for r in rows_of("UBER")}
    srcmap = {"2020-12-31": "UBER_10K_FY21_R55", "2021-12-31": "UBER_10K_FY21_R55", "2022-12-31": "UBER_10K_FY23_R50",
              "2023-12-31": "UBER_10K_FY23_R50", "2024-12-31": "UBER_10K_FY24_R51", "2025-12-31": "UBER_10K_FY25_R52",
              "2026-06-30": "UBER_10Q_Q2_26_R39"}
    for p, tup in D.UBER_INV.items():
        t = "ttm" if p == "2026-06-30" else "annual"
        tot, didi, grab, aurora, omkt, onm, note, gdebt = tup
        cur = f(rows[(p, t)]["other_financial_assets"])
        finding("UBER 优步", f"{p} ({t})",
                f"face 'Investments' (uber:MarketableAndNonMarketableInvestments; non-current; excludes separate equity-method line {D.UBER_EQUITY_METHOD[p]:,}): Didi {didi:,}, Grab {grab:,}, Aurora {aurora:,}, other marketable {omkt:,}, other non-marketable {onm:,}, related-party note {note:,}, Grab non-mkt debt {gdebt:,}",
                tot, "USD million", D.SEC_SRC[srcmap[p]], cur / 1e6, tot - cur / 1e6,
                "other_financial_assets = face Investments (custom element; companyfacts has only EquitySecuritiesWithoutReadilyDeterminableFairValueAmount)")


def uber_scen(rows):
    for r in rows:
        p, t = key(r)
        if p in D.UBER_INV:
            recompute(r, other_new=D.UBER_INV[p][0] * 1e6)
    return rows


def meta_findings():
    rows = {key(r): r for r in rows_of("META")}
    for p, (tot, ma, em) in D.META_NONMKT.items():
        t = "ttm" if p == "2026-06-30" else "annual"
        cur = f(rows[(p, t)]["other_financial_assets"])
        src = D.SEC_SRC["META_10Q_Q2_26_R41"] if t == "ttm" else D.SEC_SRC["META_10K_FY25_R54"]
        finding("META Meta Platforms", f"{p} ({t})",
                f"face 'Non-marketable equity investments' (meta:NonmarketableEquitySecuritiesCarryingValue {tot:,}) = measurement alternative {ma:,} + equity method {em:,} (data-center JV, 20%)",
                ma, "USD million", src, cur / 1e6, ma - cur / 1e6,
                "no change: equity-method part stays in IC (§6.8); pipeline already = measurement-alternative amount")
    for p, v in D.META_RESTRICTED.items():
        t = "ttm" if p == "2026-06-30" else "annual"
        finding("META Meta Platforms", f"{p} ({t})", "restricted cash counted in cash_like via CashCashEquivalentsRestrictedCash... (explains the rest of face_check's -4.22bn)",
                v, "USD million", D.SEC_SRC["META_10Q_Q2_26_R8"], None, None, "per §6.8 restricted cash stays cash-like; 1H26 non-current restricted 13,107 is large - review separately (outside OI-216)")


# ================================================================== TSM
def tsm_ncfa(p):
    s, a, b, c, em = D.TSM_NCFA[p]
    return (a + b + c) * 1e3


def tsm_findings():
    rows = {key(r): r for r in rows_of("TSM")}
    for p in ("2024-12-31", "2025-06-30", "2025-12-31", "2026-06-30"):
        s, a, b, c, em = D.TSM_NCFA[p]
        url, ref = D.TSM_SRC[s]
        t = {"2024-12-31": "annual", "2025-12-31": "annual", "2026-06-30": "ttm"}.get(p)
        cur = f(rows[(p, t)]["other_financial_assets"]) if t and (p, t) in rows else None
        val = tsm_ncfa(p)
        finding("TSM 台积电", f"{p} ({t or 'interim comparative'})",
                f"non-current financial assets: FVTPL {a:,}k + FVTOCI {b:,}k + amortized cost {c:,}k (equity-method {em:,}k excluded)",
                val / 1e6, "TWD million", f"{url} | {ref}", None if cur is None else cur / 1e6, None if cur is None else (val - cur) / 1e6,
                {"2025-12-31": "fill override other_financial_assets (FY2025 row); TTM row then carries it under the 15-month rule",
                  "2026-06-30": "fill override other_financial_assets (TTM row) - or leave blank to carry FY2025 134,337 m (see summary)",
                  "2024-12-31": "reference: companyfacts FY2024 row already equals the face total (no gap)",
                  "2025-06-30": "reference: 1H25 comparative (not a pipeline row)"}[p])
    em25 = D.TSM_EM["2025-12-31"][1] * 1e3
    emttm = em25 + (D.TSM_EM["2026-06-30"][1] - D.TSM_EM["2025-06-30"][1]) * 1e3
    finding("TSM 台积电", "2025-12-31 (annual)", "share of profits of associates (equity method; override row has equity_method_income blank)",
            em25 / 1e6, "TWD million", D.TSM_SRC["20F2025"][0] + " R4", 0.0, em25 / 1e6, "fill override equity_method_income (EBIT = op + em)")
    finding("TSM 台积电", "2026-06-30 (ttm)", "share of profits of associates TTM = FY2025 5,488.5m + 1H26 3,123.4m - 1H25 2,589.3m",
            emttm / 1e6, "TWD million", D.TSM_SRC["FS2Q26"][0] + " p.4", 0.0, emttm / 1e6, "fill override equity_method_income")


def tsm_scen(ttm_value="2q26"):
    def fn(rows):
        for r in rows:
            p, t = key(r)
            if (p, t) == ("2025-12-31", "annual"):
                recompute(r, d_ebit=D.TSM_EM["2025-12-31"][1] * 1e3, other_new=tsm_ncfa("2025-12-31"))
            elif (p, t) == ("2026-06-30", "ttm"):
                em = (D.TSM_EM["2025-12-31"][1] + D.TSM_EM["2026-06-30"][1] - D.TSM_EM["2025-06-30"][1]) * 1e3
                other = tsm_ncfa("2026-06-30") if ttm_value == "2q26" else tsm_ncfa("2025-12-31")
                recompute(r, d_ebit=em, other_new=other)
        return rows
    return fn


def tsm_bonds_scen(rows):
    """Side check (outside OI-216): add non-current bonds payable + IFRS lease liabilities missing from companyfacts annual rows."""
    import json as _j
    facts = _j.load((REPO / "data/raw/overseas_statements/sec/TSM.json").open())["facts"]["ifrs-full"]

    def val(c, end):
        es = [e for e in facts.get(c, {}).get("units", {}).get("TWD", []) if e["end"] == end and e.get("form", "").startswith("20-F")]
        return max(es, key=lambda e: e["filed"])["val"] if es else None
    for r in rows:
        p, t = key(r)
        if t != "annual" or r["source"] != "SEC companyfacts ifrs-full":
            continue
        lt = val("LongtermBorrowings", p)
        bonds = val("NoncurrentPortionOfNoncurrentBondsIssued", p)
        if lt is not None and bonds:
            recompute(r, d_debt=bonds)
    return rows


# ================================================================== minor / side findings
OOIL_AC_NC = {  # non-current 'Investments at amortised cost' (US$'000) -> F10 长期投资 (left in IC by HK_OTHER_FIN_KEYS)
    "2021-12-31": ("AR2022", 98335), "2022-12-31": ("AR2023", 52966), "2023-12-31": ("AR2024", 52926),
    "2024-12-31": ("AR2025", 47889), "2025-12-31": ("AR2025", 17000), "2026-06-30": ("IR2026", 17000)}


def f10_balance(code):
    d = json.load((REPO / f"data/raw/overseas_statements/hk/{code}_balance.json").open(encoding="utf-8"))
    per = {}
    for r in d:
        per.setdefault(str(r["REPORT_DATE"])[:10], {})[r["STD_ITEM_NAME"]] = f(r["AMOUNT"])
    return per


OOIL_BAL = f10_balance("00316")


def ooil_minor_findings():
    rows = {key(r): r for r in rows_of("00316")}
    for p, (src, usd) in OOIL_AC_NC.items():
        url, ref = D.OOIL_SRC[src]
        t = "ttm" if p == "2026-06-30" else "annual"
        f10 = OOIL_BAL.get(p, {}).get("长期投资")
        cur = f(rows[(p, t)]["other_financial_assets"])
        finding("00316 东方海外国际", f"{p} ({t})", "[minor] non-current 'Investments at amortised cost' (bonds; interest on them is excluded from EBIT above) = F10 长期投资",
                usd, "USD thousand", f"{url} | balance sheet", 0.0, usd,
                f"optional supplement other_financial_assets += F10 长期投资 {0 if f10 is None else f10/1e9:.4f} bn CNY (pipeline other_financial_assets {cur/1e9:.4f} bn CNY excludes it); V effect +0.1%")


def ooil_minor_scen(rows):
    rows = ooil_scen(rows)
    for r in rows:
        p, t = key(r)
        if p in OOIL_AC_NC:
            f10 = OOIL_BAL.get(p, {}).get("长期投资") or 0.0
            recompute(r, d_other=f10)
    return rows


def side_findings():
    finding("09618 京东集团", "2023-12-31 (annual)", "[side, outside OI-216] repo raw F10 cache (fetched 2026-09-03) lacks 现金及等价物/短期投资/股东权益/总权益/长期贷款 for FY2023 -> row has cash_like 7.506bn, no equity, no IC; live F10 (queried 2026-09-28) now returns them",
            197652, "RMB million (cash-like = cash 71,892 + restricted 7,506 + ST investments 118,254; also parent equity 231,858, total equity 296,380 incl. mezzanine 614)",
            "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_HKF10_FN_BALANCE_PC (SECUCODE 09618.HK, REPORT_DATE 2023-12-31); AR2024 balance sheet PDF p.266",
            7506, 190146, "run fetch_overseas_statements.py --refresh (no maintenance row needed)")
    finding("TSM 台积电", "2019-2024 (annual)", "[side, outside OI-216] IFRS lt_debt_noncurrent candidates are alternatives: LongtermBorrowings wins, NoncurrentPortionOfNoncurrentBondsIssued (bonds payable) dropped; lease liabilities not mapped for IFRS",
            926604.5, "TWD million (bonds payable at 2024-12-31; 2023 913,899.8; 2022 834,336.4; 2021 610,070.6)",
            "SEC companyfacts ifrs-full; 20-F FY2024 balance sheet R2", 92148.8, 926604.5,
            "make bonds a separate additive debt layer for ifrs-full (e.g. key bonds_noncurrent) in compose_debt; engine replay: V -7.7% vs OI-216-fixed V (ROIC0 61.9% -> 40.7%)")
    finding("TSM 台积电", "2025-12-31 / 2026-06-30", "[side] override cash_like excludes current 'Other financial assets' (59,702.9 m / 80,032.5 m) while the ifrs-full tag group counts OtherCurrentFinancialAssets for 2015-2024 rows",
            59702.9, "TWD million", D.TSM_SRC["FS2Q26"][0], 0.0, None,
            "decide one treatment (note 21: interest on 'government grants receivable and others' - partly operating); |V effect| ~0.2%")
    finding("09618 京东集团", "all periods", "[side] HK F10 maps JD's US-GAAP operating lease liabilities to 融资租赁负债 -> counted as interest-bearing debt (SEC path excludes operating leases)",
            35416, "RMB million (1H26: 10,049 current + 25,367 non-current)", "HK F10 balance; JD AR2025 balance sheet PDF p.263", 35416, None,
            "caliber question for the user (≈12.6 CNY/share of net debt); not changed here")


# ================================================================== run
ooil_findings(); ooil_minor_findings(); hdl_findings(); jd_findings(); nvda_findings(); uber_findings(); meta_findings(); tsm_findings(); side_findings()
run("00316", [("OI-216: EBIT minus interest income in other operating income", ooil_scen),
              ("OI-216 + minor: non-current amortised-cost investments as other financial assets", ooil_minor_scen)])
run("06862", [("OI-216: EBIT minus financial interest income in other income", hdl_scen)])
run("09618", [("OI-216: EBIT plus equity-method share", jd_scen(em=True)),
              ("OI-216 + non-EM investments as other financial assets", jd_scen(em=True, bs=True)),
              ("above + fill 2023 F10 hole (cash, ST inv, equity) [side]", jd_scen(em=True, bs=True, fill2023=True))])
run("NVDA", [("OI-216: + current marketable equity securities (EquitySecuritiesFvNi)", nvda_scen)])
run("UBER", [("OI-216: other financial assets = face Investments", uber_scen)])
run("META", [])
run("TSM", [("OI-216: override other_financial_assets FY25 134.3bn + TTM 209.8bn (2Q26 FS), em filled", tsm_scen("2q26")),
            ("OI-216: override FY25 134.3bn, TTM carried FY25 value, em filled", tsm_scen("carry")),
            ("side: + bonds payable in companyfacts annual rows 2019-2024 (outside OI-216)",
             lambda rows: tsm_bonds_scen(tsm_scen("2q26")(rows)))])

with (OUT / "oi216_findings.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["company", "period", "item", "value", "currency", "source", "current_pipeline_value", "gap", "proposed_fix"])
    w.writeheader(); w.writerows(FINDINGS)
(OUT / "oi216_v_effects.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1, default=str))
def _fmt(x, spec):
    return "" if x is None else format(x, spec)


for r in RESULTS:
    print(r["code"].ljust(6), r["scenario"][:78].ljust(78), r["status"].ljust(9), "V=" + _fmt(r.get("value"), "10.3f"),
          "Vtrade=" + _fmt(r.get("v_trade"), "9.2f"), "P/V=" + _fmt(r.get("pv"), ".3f"), "mode=" + str(r.get("mode")),
          "r0=" + _fmt(r.get("ratio0"), ".4f"), "roic0=" + _fmt(r.get("roic0"), ".4f"), "g0=" + _fmt(r.get("g0"), ".4f"),
          "ndps=" + _fmt(r.get("net_debt_ps"), ".3f"), "w/v=" + _fmt(r.get("peak_w"), ".2f") + "/" + _fmt(r.get("trough_w"), ".2f"),
          (r.get("reason") or "")[:60])
print(len(FINDINGS), "findings rows")

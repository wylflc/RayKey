"""Write proposed rows (scratch only): proposed_supplements.csv and proposed_tsm_override_rows.csv."""
import csv
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import oi216_data as D  # noqa: E402

REPO = Path("/gpfs/scratch1/shared/zwang/mm_quant/RayKey")
OUT = Path(__file__).resolve().parents[1]
DATES = {  # publication dates of the documents actually read (HKEX / EDGAR listing)
    ("00316", "AR2025"): "2026-04-22", ("00316", "AR2024"): "2025-04-16", ("00316", "AR2023"): "2024-04-24",
    ("00316", "AR2022"): "2023-04-25", ("00316", "AR2021"): "2022-04-27", ("00316", "AR2020"): "2021-04-28",
    ("00316", "IA2026"): "2026-08-27", ("00316", "IR2026"): "2026-09-23",
    ("06862", "AR2025"): "2026-04-24", ("06862", "AR2024"): "2025-04-24", ("06862", "AR2023"): "2024-04-25",
    ("06862", "AR2022"): "2023-04-26", ("06862", "AR2021"): "2022-04-26", ("06862", "AR2020"): "2021-04-26",
    ("06862", "IA2026"): "2026-08-25",
    ("09618", "AR2025"): "2026-04-16", ("09618", "AR2024"): "2025-04-17", ("09618", "AR2023"): "2024-04-18",
    ("09618", "AR2022"): "2023-04-20", ("09618", "AR2021"): "2022-04-28", ("09618", "AR2020"): "2021-04-18",
    ("09618", "IA2026"): "2026-08-13",
}
IA = {"00316": ("https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0827/2026082701643.pdf", "2026 Interim Results announcement PDF p.15 note 7 (1H26 and 1H25 columns)"),
      "06862": ("https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0825/2026082501119.pdf", "Interim results announcement PDF p.22 note 4 (1H26 and 1H25 columns)")}


def f10(code, kind):
    d = json.load((REPO / f"data/raw/overseas_statements/hk/{code}_{kind}.json").open(encoding="utf-8"))
    per = {}
    for r in d:
        per.setdefault(str(r["REPORT_DATE"])[:10], {})[r["STD_ITEM_NAME"]] = float(r["AMOUNT"]) if r["AMOUNT"] not in (None, "") else None
    return per


rows = []
FIELDS = ["market", "security_code", "security_name", "period", "period_kind", "field", "value", "unit", "original_value",
          "original_unit", "fx_to_report", "evidence_date", "source_url", "source_ref", "note"]


def add(**kw):
    rows.append({k: kw.get(k, "") for k in FIELDS})


# 00316: financial income inside Other operating income (subtract from EBIT), CNY at the F10-implied FX
inc = f10("00316", "income")
for p, v in sorted(D.OOIL.items()):
    src, rev, ooi, op, b, fs, ac, fvi, distr, div, fvoci = v
    fx = inc[p]["营业额"] / (rev * 1e3)
    usd = (b + fs + ac + fvi) * 1e3
    kind = "annual" if p.endswith("12-31") else "interim_ytd"
    url, ref = D.OOIL_SRC[src]
    ev = DATES[("00316", src)]
    add(market="HK", security_code="00316", security_name="东方海外国际", period=p, period_kind=kind,
        field="ebit_financial_income_in_operating", value=round(usd * fx), unit="CNY", original_value=round(usd),
        original_unit="USD", fx_to_report=round(fx, 6), evidence_date=ev, source_url=url, source_ref=ref,
        note=f"interest from banks {b:,}k + fellow-subsidiary deposits {fs:,}k + amortised-cost investments {ac:,}k + FVTPL interest {fvi:,}k; "
             f"inside Other operating income {ooi:,}k (inside Operating profit); FX = F10 营业额 / reported revenue")
# 06862: financial interest inside Other income (subtract), RMB
for p, v in sorted(D.HDL.items()):
    src, tot, bank, ofa, fvoci, rental = v
    kind = "annual" if p.endswith("12-31") else "interim_ytd"
    url, ref = D.HDL_SRC[src]
    ev = DATES[("06862", src)]
    add(market="HK", security_code="06862", security_name="海底捞", period=p, period_kind=kind,
        field="ebit_financial_income_in_operating", value=(bank + ofa + fvoci) * 1000, unit="CNY",
        original_value=(bank + ofa + fvoci) * 1000, original_unit="CNY", fx_to_report=1, evidence_date=ev, source_url=url,
        source_ref=ref, note=f"interest on bank deposits {bank:,}k + other financial assets {ofa:,}k + FVTOCI/FVTPL {fvoci:,}k; "
                             f"rental-deposit interest {rental:,}k kept in EBIT; other income total {tot:,}k = F10 其他收入")
# 09618: equity-method share (add to EBIT)
for p, v in sorted(D.JD_EM.items()):
    src, em, ii, on = v
    if p < "2017-01-01":
        continue
    kind = "annual" if p.endswith("12-31") else "interim_ytd"
    url, ref = D.JD_SRC[src]
    add(market="HK", security_code="09618", security_name="京东集团", period=p, period_kind=kind, field="equity_method_income",
        value=em * 10**6, unit="CNY", original_value=em * 10**6, original_unit="CNY", fx_to_report=1,
        evidence_date=DATES[("09618", src)], source_url=url, source_ref=ref,
        note="Share of results of equity investees (below Income from operations); F10 溢利其他项目 = this + Others,net"
             + ("" if ii is None else f"; Others,net {on:,}m incl. interest income {ii:,}m (not in EBIT)"))
# 09618: non-current financial assets (replace other_financial_assets)
carry = None
for p, v in sorted(D.JD_BS.items()):
    src, eq, em, msoi = v
    if em is not None:
        nonem = eq - em
        carry = nonem
        note = f"'Marketable securities and other investments' {msoi:,}m + ('Investments in equity investees' {eq:,}m - equity method {em:,}m)"
    else:
        nonem = carry
        note = (f"ESTIMATE: 'Marketable securities and other investments' {msoi:,}m (announcement balance sheet) + non-equity-method part of "
                f"'Investment in equity investees' carried from FY2025 ({carry:,}m); 1H26 equity-method split not disclosed (IFRS reconciliation "
                f"moves 28,100m of the 58,040m to FVTPL, which also includes equity-method PE funds, ~6.9bn at FY2025)")
    kind = "balance_annual" if p.endswith("12-31") else "balance_interim"
    url, ref = D.JD_SRC[src]
    add(market="HK", security_code="09618", security_name="京东集团", period=p, period_kind=kind, field="other_financial_assets",
        value=(msoi + nonem) * 10**6, unit="CNY", original_value=(msoi + nonem) * 10**6, original_unit="CNY", fx_to_report=1,
        evidence_date=DATES[("09618", src)], source_url=url, source_ref=ref, note=note)
# UBER: face Investments (replace other_financial_assets)
u_src = {"2020-12-31": ("UBER_10K_FY21_R55", "2022-02-24"), "2021-12-31": ("UBER_10K_FY21_R55", "2022-02-24"),
         "2022-12-31": ("UBER_10K_FY23_R50", "2024-02-15"), "2023-12-31": ("UBER_10K_FY23_R50", "2024-02-15"),
         "2024-12-31": ("UBER_10K_FY24_R51", "2025-02-14"), "2025-12-31": ("UBER_10K_FY25_R52", "2026-02-13"),
         "2026-06-30": ("UBER_10Q_Q2_26_R39", "2026-08-05")}
for p, v in sorted(D.UBER_INV.items()):
    s, ev = u_src[p]
    add(market="US", security_code="UBER", security_name="优步", period=p,
        period_kind="balance_interim" if p == "2026-06-30" else "balance_annual", field="other_financial_assets",
        value=v[0] * 10**6, unit="USD", original_value=v[0] * 10**6, original_unit="USD", fx_to_report=1, evidence_date=ev,
        source_url=D.SEC_SRC[s], source_ref="face line uber:MarketableAndNonMarketableInvestments ('Investments')",
        note=f"Didi {v[1]:,} + Grab {v[2]:,} + Aurora {v[3]:,} + other marketable {v[4]:,} + other non-marketable {v[5]:,} + related-party note {v[6]:,} + Grab non-mkt debt {v[7]:,}; equity-method line {D.UBER_EQUITY_METHOD[p]:,} excluded (stays in IC)")
# 00316 optional: other_financial_assets incl. non-current amortised-cost investments (F10 长期投资)
bal = f10("00316", "balance")
for p in ("2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31", "2026-06-30"):
    x = bal[p]
    base = sum(x.get(k) or 0.0 for k in ("现金及等价物(非流动)", "中长期存款", "证券投资", "指定以公允价值记账之金融资产", "其他金融资产(非流动)"))
    lt = x.get("长期投资") or 0.0
    add(market="HK", security_code="00316", security_name="东方海外国际", period=p,
        period_kind="balance_interim" if p.endswith("06-30") else "balance_annual", field="other_financial_assets",
        value=round(base + lt), unit="CNY", original_value="", original_unit="", fx_to_report="",
        evidence_date=DATES[("00316", {"2021-12-31": "AR2021", "2022-12-31": "AR2022", "2023-12-31": "AR2023", "2024-12-31": "AR2024", "2025-12-31": "AR2025", "2026-06-30": "IR2026"}[p])],
        source_url=D.OOIL_SRC[{"2021-12-31": "AR2021", "2022-12-31": "AR2022", "2023-12-31": "AR2023", "2024-12-31": "AR2024", "2025-12-31": "AR2025", "2026-06-30": "IR2026"}[p]][0],
        source_ref="balance sheet 'Investments at amortised cost' (non-current) = F10 长期投资",
        note=f"OPTIONAL/minor: F10 other_financial_assets {base:,.0f} + 长期投资 {lt:,.0f} (bonds at amortised cost whose interest is removed from EBIT)")

with (OUT / "proposed_supplements.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader(); w.writerows(rows)

# TSMC: the two existing override rows with the proposed column values filled
src = list(csv.DictReader((REPO / "data/reference/overseas_statement_overrides.csv").open(encoding="utf-8-sig")))
hdr = list(src[0].keys())
out = []
for r in src:
    if r["security_code"] != "TSM":
        continue
    r = dict(r)
    if r["period"] == "2025-12-31":
        r["other_financial_assets"] = str(134337102000)
        r["equity_method_income"] = str(5488500000)
        r["source"] = r["source"] + "; noncurrent financial assets & equity-method share from FY2025 audited consolidated FS (6-K 2026-02-26 / 20-F 2026-04-16)"
    elif r["period"] == "2026-06-30":
        r["other_financial_assets"] = str(209809336000)
        r["equity_method_income"] = str(6022620000)
        r["source"] = r["source"] + "; noncurrent financial assets from 2Q26 reviewed consolidated FS (6-K 2026-08-14); em TTM = 5,488.5 + 3,123.4 - 2,589.3 m"
    out.append(r)
with (OUT / "proposed_tsm_override_rows.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=hdr, lineterminator="\n")
    w.writeheader(); w.writerows(out)
print(len(rows), "supplement rows;", len(out), "TSM override rows")

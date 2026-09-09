"""Audit raw and archived WC classifications without changing their source records."""
from collections import Counter
import csv
import json
import math
from pathlib import Path
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs as ri


def write_csv(name, rows):
    with (EXP / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def main():
    with (ROOT / "data/processed/a_share_pool_model_bands_adopted.csv").open() as f:
        core = {r["security_code"] for r in csv.DictReader(f)}
    stats = {}; conflicts = []; recent = []; mappings = Counter()
    for kind, path in [("current", ri.STMT_DIR / "balance.csv"),
                       ("archived", ri.STMT_DIR / "superseded/balance.csv")]:
        count = Counter(); codes = set()
        if not path.exists():
            continue
        with path.open() as f:
            for row in csv.DictReader(f):
                if (row.get("org_table") or "").startswith(ri.FINANCIAL_TABLE_PREFIXES):
                    count["financial_rows_skipped"] += 1
                    continue
                wc = ri.working_capital_inputs(row)
                legacy = ri._sum(row, ri.WC_ASSET_FIELDS) - ri._sum(row, ri.WC_LIAB_FIELDS)
                count["nonfinancial_rows"] += 1
                count["receivable:" + wc.receivable_basis] += 1
                count["payable:" + wc.payable_basis] += 1
                if wc.financing_receivables:
                    count["financing_receivables_nonzero"] += 1
                if wc.reported is not None and abs(wc.reported - legacy) > .01:
                    count["dedup_changes_wc"] += 1; codes.add(row["SECURITY_CODE"])
                if wc.operating is not None and abs(wc.operating - legacy) > .01:
                    count["operating_changes_wc"] += 1
                if wc.operating is None:
                    count["invalid_operating_wc"] += 1
                for name, total, first, second, basis in [
                    ("receivable", "NOTE_ACCOUNTS_RECE", "ACCOUNTS_RECE", "NOTE_RECE", wc.receivable_basis),
                    ("payable", "NOTE_ACCOUNTS_PAYABLE", "ACCOUNTS_PAYABLE", "NOTE_PAYABLE", wc.payable_basis),
                ]:
                    if "conflict" not in basis and "invalid" not in basis:
                        continue
                    a, b, c = [ri._num(row.get(k)) for k in (total, first, second)]
                    classification = "aggregate_and_components_differ"
                    if name == "receivable" and all(v is not None for v in (a, b, c)):
                        if wc.financing_receivables and math.isclose(a + wc.financing_receivables, b+c, abs_tol=.01, rel_tol=1e-12):
                            classification = "financing_reclassification"
                        elif row["SECURITY_CODE"] in {"000022", "001872"} and row["REPORT_DATE"][:10] == "2017-12-31":
                            classification = "year_end_vs_next_opening"
                        elif math.isclose(a, c, abs_tol=.01, rel_tol=1e-12):
                            classification = "historical_aggregate_equals_notes"
                        elif math.isclose(a, b, abs_tol=.01, rel_tol=1e-12):
                            classification = "aggregate_equals_accounts"
                    mappings[kind+":"+classification] += 1
                    conflicts.append({"version": kind, "security_code": row["SECURITY_CODE"],
                        "security_name": row["SECURITY_NAME_ABBR"], "report_date": row["REPORT_DATE"],
                        "notice_date": row.get("NOTICE_DATE", ""), "update_date": row.get("UPDATE_DATE", ""),
                        "superseded_at": row.get("superseded_at", ""), "group": name, "total": a,
                        "account_component": b, "note_component": c, "financing_receivables": wc.financing_receivables,
                        "classification": classification, "selected_basis": basis,
                        "selected_group": a if a is not None else ((b or 0)+(c or 0))})
                if kind == "current" and row["SECURITY_CODE"] in core and row["REPORT_DATE"] >= "2020-12-31":
                    recent.append({"security_code": row["SECURITY_CODE"], "security_name": row["SECURITY_NAME_ABBR"],
                        "report_date": row["REPORT_DATE"], "legacy_wc": legacy, "dedup_wc": wc.reported,
                        "operating_wc": wc.operating, "financing_receivables": wc.financing_receivables,
                        "receivable_basis": wc.receivable_basis, "payable_basis": wc.payable_basis})
        stats[kind] = {**dict(count), "codes_with_dedup_change": len(codes)}
    write_csv("source_conflicts.csv", conflicts)
    write_csv("core_annual_wc.csv", recent)
    result = {"unit": "raw statement rows, not distinct issuers", "counts": stats,
              "conflict_classes": dict(mappings),
              "limit": "Grouping uses reported totals. A conflict marker is not a claim that every historical source field was independently audited."}
    (EXP / "source_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Reproduce the aggregate/component audit from the frozen balance CSV."""
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]


def number(value):
    try:
        x = Decimal(value)
        return x if x.is_finite() else None
    except (InvalidOperation, TypeError):
        return None


def main():
    groups = {
        "receivables": ("NOTE_ACCOUNTS_RECE", "ACCOUNTS_RECE", "NOTE_RECE"),
        "payables": ("NOTE_ACCOUNTS_PAYABLE", "ACCOUNTS_PAYABLE", "NOTE_PAYABLE"),
    }
    counts = {name: Counter() for name in groups}
    differences = []
    with (ROOT / "data/raw/financials_statements/balance.csv").open() as f:
        for row in csv.DictReader(f):
            for name, fields in groups.items():
                values = [number(row.get(field)) for field in fields]
                if any(x is None for x in values):
                    continue
                total, first, second = values
                counts[name]["aggregate_and_both_parts"] += 1
                if abs(total - first - second) <= Decimal("0.01"):
                    counts[name]["equal_within_cent"] += 1
                else:
                    counts[name]["different_total"] += 1
                    differences.append({
                        "group": name, "security_code": row["SECURITY_CODE"],
                        "report_date": row["REPORT_DATE"], "total": str(total),
                        "first": str(first), "second": str(second),
                        "difference": str(total - first - second),
                    })
    result = {"source": "data/raw/financials_statements/balance.csv",
              "unit": "raw statement rows, not distinct companies",
              "equality_tolerance_yuan": "0.01", "groups": counts}
    (EXP / "wc_source_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if differences:
        with (EXP / "wc_source_differences.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(differences[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(differences)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

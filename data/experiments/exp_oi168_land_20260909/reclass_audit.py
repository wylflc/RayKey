"""OI-168 落地证据：2019 年新金融工具准则切换（应收票据 → 应收款项融资）在三种营运资金口径下的断层。

对实验宇宙（exp_oi168_wc_20260909/codes.txt）非金融公司，取 2018／2019 年报的应收组、应付组，按
legacy（合计＋明细相加）、reported（合计或明细）、operating（reported＋FINANCE_RECE）计算
「应收 − 应付」及其 2018→2019 变动；另统计全部非金融公司 FINANCE_RECE 首次出现年份。
"""
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXP = Path(__file__).resolve().parent
FIN = ("RPT_F10_FINANCE_B", "RPT_F10_FINANCE_S", "RPT_F10_FINANCE_I")


def num(x):
    try:
        return float(x) if x not in ("", None, "None") else None
    except ValueError:
        return None


def main():
    codes = {l.strip() for l in (EXP.parent / "exp_oi168_wc_20260909/codes.txt").read_text().splitlines() if l.strip()}
    by = defaultdict(dict)
    with (ROOT / "data/raw/financials_statements/balance.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("org_table") or "").startswith(FIN):
                continue
            d = row["REPORT_DATE"][:10]
            if not d.endswith("12-31"):
                continue
            g = lambda k: num(row.get(k))
            t, a, n, fin = g("NOTE_ACCOUNTS_RECE"), g("ACCOUNTS_RECE"), g("NOTE_RECE"), g("FINANCE_RECE")
            tp, ap, np_ = g("NOTE_ACCOUNTS_PAYABLE"), g("ACCOUNTS_PAYABLE"), g("NOTE_PAYABLE")
            rec = t if t is not None else (a or 0) + (n or 0)
            pay = tp if tp is not None else (ap or 0) + (np_ or 0)
            by[row["security_code"].zfill(6)][d[:4]] = {
                "legacy": (t or 0) + (a or 0) + (n or 0) - ((tp or 0) + (ap or 0) + (np_ or 0)),
                "reported": rec - pay, "operating": rec - pay + (fin or 0),
                "notes": n or 0, "financing": fin or 0, "name": row.get("SECURITY_NAME_ABBR", "")}
    first = Counter()
    for ys in by.values():
        yrs = sorted(y for y, v in ys.items() if v["financing"] > 0)
        if yrs:
            first[yrs[0]] += 1
    rows = []
    for code, ys in sorted(by.items()):
        if code in codes and "2018" in ys and "2019" in ys:
            a, b = ys["2018"], ys["2019"]
            rows.append({"security_code": code, "security_name": b["name"], "notes_2018": a["notes"],
                         "financing_2019": b["financing"],
                         **{f"delta_{k}": b[k] - a[k] for k in ("legacy", "reported", "operating")}})
    with (EXP / "reclass_2018_2019.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    summary = {"nonfinancial_codes": len(by), "universe_codes_with_2018_2019": len(rows),
               "notes2018_and_financing2019": sum(1 for r in rows if r["notes_2018"] > 0 and r["financing_2019"] > 0),
               "financing_first_year": dict(sorted(first.items())),
               "delta_rec_minus_pay_2018_2019": {k: {"median_yi": round(statistics.median(r[f"delta_{k}"] for r in rows) / 1e8, 2),
                                                    "negative_codes": sum(1 for r in rows if r[f"delta_{k}"] < 0)}
                                                 for k in ("legacy", "reported", "operating")}}
    (EXP / "reclass_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

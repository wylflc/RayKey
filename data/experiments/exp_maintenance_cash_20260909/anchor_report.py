"""Compare the existing descriptive anchors on the same available sample."""
import csv
import json
from pathlib import Path
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
from roic_anchor_check import ANCHORS, price_at, spearman
import build_historical_valuation_bands as bhv


def main():
    tags = ("BASE", "WCREP", "MC050", "MC100", "MC150")
    keys = {(a[0], a[2]) for a in ANCHORS}
    bands = {}
    for tag in tags:
        with (EXP / "val" / tag / "roic_bands_base.csv").open() as f:
            bands[tag] = {(r["security_code"], r["report_date"]): r for r in csv.DictReader(f)
                          if (r["security_code"], r["report_date"]) in keys}
    prices = {code: bhv.load_ohlcv(code) for code, _ in keys}
    actions = bhv.load_actions()
    rows = []
    for code, name, period, label, _ in ANCHORS:
        key = (code, period)
        available = bands["BASE"][key]["available_at"]
        first = price_at(prices[code], available)
        target = str(int(available[:4]) + 3) + available[4:]
        last = price_at(prices[code], target, forward=True)
        forward = (last[1] * bhv.split_factor(actions.get(code, []), first[0], last[0]) / first[1] - 1
                   if first and last and last[0] > first[0] else None)
        common = all(bands[t][key]["status"] == "ok" for t in tags) and first is not None
        for tag in tags:
            r = bands[tag][key]
            assert r["available_at"] == available
            rows.append({"arm": tag, "security_code": code, "security_name": name, "report_date": period,
                         "label": label, "available_at": available, "status": r["status"], "reason": r["reason"],
                         "pv": first[1] / float(r["intrinsic_value"]) if first and r["status"] == "ok" else None,
                         "forward_3y_ex_dividend": forward, "common_sample": common})
    with (EXP / "anchor_rows.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    result = {}
    for tag in tags:
        valid = [r for r in rows if r["arm"] == tag and r["pv"] is not None]
        same = [r for r in valid if r["common_sample"]]
        cheap = [r["pv"] for r in same if r["label"] == "低估"]
        expensive = [r["pv"] for r in same if r["label"] == "高估"]
        fwd = [r for r in same if r["forward_3y_ex_dividend"] is not None]
        result[tag] = {"available_anchors": len(valid), "common_anchors": len(same),
                       "common_pairs": len(cheap) * len(expensive),
                       "common_auc": sum(c < e for c in cheap for e in expensive) / (len(cheap) * len(expensive)),
                       "common_spearman": spearman([r["pv"] for r in fwd], [r["forward_3y_ex_dividend"] for r in fwd])}
    (EXP / "anchor_comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

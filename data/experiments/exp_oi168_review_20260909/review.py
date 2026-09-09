"""Read-only OI-168 review; writes evidence only into this review directory."""
import contextlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs as ri
import screen_daily_volume_price_signals as scan
import sweep_backtest_configs as sw


def main():
    result = {"reviewed_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    old_exp = ROOT / "data/experiments/exp_oi168_wc_20260909"
    with (old_exp / "summary_rows.csv").open() as f:
        old = {(r["group"], r["start"]): r for r in csv.DictReader(f)
               if r["arm"] == "WCOPRAWSEP09" and r["group"] in ("full", "A")}
    with (ROOT / "data/backtest/scan_summaries.csv").open() as f:
        new = {r["扫描标签"]: r for r in csv.DictReader(f) if r["扫描标签"].startswith("BASE")}
    mismatches = []; checked = 0
    for (group, start), row in old.items():
        candidate = new[sw.summary_tag("BASE", start, "fixed" if group == "A" else "")]
        for field in (*sw.FIELDS, "前五赢家", "首个净值日", "末次净值日"):
            checked += 1
            if row[field] != candidate[field]: mismatches.append([group, start, field])
    result["baseline_reproduction"] = {"paths": len(old), "fields_checked": checked, "mismatches": mismatches}

    old_module = types.ModuleType("oi168_review_previous_roic")
    old_module.__file__ = str(ROOT / "scripts/roic_inputs.py")
    sys.modules[old_module.__name__] = old_module
    source = subprocess.check_output(["git", "show", "e7cf130e:scripts/roic_inputs.py"], cwd=ROOT, text=True)
    exec(compile(source, old_module.__file__, "exec"), old_module.__dict__)
    n = 0; mismatches = []
    mappings = [("working_capital", "working_capital_operating"), ("working_capital_legacy", "working_capital"),
                ("working_capital_reported", "working_capital_reported"), ("invested_capital", "invested_capital"),
                ("interest_debt", "interest_debt"), ("excess_cash", "excess_cash"), ("nopat", "nopat")]
    for path in (ri.STMT_DIR / "balance.csv", ri.STMT_DIR / "superseded/balance.csv"):
        with path.open() as f:
            for row in csv.DictReader(f):
                if (row.get("org_table") or "").startswith(ri.FINANCIAL_TABLE_PREFIXES): continue
                code, period = row["SECURITY_CODE"], row["REPORT_DATE"][:10]
                parts = {"balance": row, "income": {"NOTICE_DATE": row.get("NOTICE_DATE") or "2026-09-09",
                         "TOTAL_OPERATE_INCOME": "100000000", "TOTAL_PROFIT": "10000000"}}
                a = old_module._year_from_parts(code, period, parts, False)
                b = ri._year_from_parts(code, period, parts, False)
                for current, previous in mappings:
                    if getattr(a, previous) != getattr(b, current): mismatches.append([code, period, current])
                n += 1
    result["default_field_migration"] = {"real_balance_rows": n, "fields_checked": n * len(mappings),
        "income": "Identical synthetic income on both sides to isolate the migration; not an earnings audit.",
        "mismatches": mismatches}

    processed = ROOT / "data/processed"
    with (processed / "daily_buy_candidates.csv").open() as f: original = list(csv.DictReader(f))
    current = [dict(r) for r in original]
    with contextlib.redirect_stdout(io.StringIO()):
        for prefix, file in (("model", "a_share_pool_model_bands_adopted.csv"), ("hold", "a_share_pool_model_bands_hold.csv")):
            bands = scan.load_model_bands(processed / file, "2026-09-10")
            scan.attach_model_pv(current, bands, "2026-09-09", None, prefix=prefix)
    changes = []; flips = []
    def eligible(r):
        values = [scan.to_float(r[k]) for k in ("model_pv", "close", "ma20", "ma60")]
        return (all(v is not None for v in values) and values[0] <= scan.SEC93_BUY_LINE
                and values[1] > values[2] > values[3] and r["signal_state"] == "ok" and r["review_frozen"] == "False")
    for a, b in zip(original, current):
        ov, nv = scan.to_float(a["model_intrinsic_value"]), scan.to_float(b["model_intrinsic_value"])
        opv, npv = scan.to_float(a["model_pv"]), scan.to_float(b["model_pv"])
        out = {"security_code": a["security_code"], "security_name": a["security_name"], "close": a["close"],
               "cached_value": ov, "current_value": nv, "cached_pv": opv, "current_pv": npv,
               "eligible_cached": eligible(a), "eligible_current": eligible(b)}
        if ov and nv and abs(ov - nv) > .0001: changes.append(out)
        if opv is not None and npv is not None and (opv <= scan.SEC93_BUY_LINE) != (npv <= scan.SEC93_BUY_LINE): flips.append(out)
    with (EXP / "stale_candidate_values.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(changes[0]), lineterminator="\n"); w.writeheader(); w.writerows(changes)
    result["daily_candidates"] = {"cached_rows": len(original), "changed_values": len(changes), "line_crossings": flips,
        "mechanical_eligible_before": sum(eligible(r) for r in original),
        "mechanical_eligible_after": sum(eligible(r) for r in current),
        "scope": "Same cached closes/MAs, no network price refresh, no account/funding/order execution simulation."}

    with tempfile.TemporaryDirectory() as folder:
        p = Path(folder); panel = p / "panel.csv"
        panel.write_text("security_code,effective_from,effective_to\n000001,2000-01-01,2099-12-31\n")
        for name, k in (("current", 1793), ("next", 1809)):
            with (p / (name + ".csv")).open("w", newline="") as f:
                w = csv.writer(f); w.writerow(["security_code", "date", "valuation_ratio"])
                for i in range(10000):
                    w.writerow(["000001", "2026-09-09", .5+.5*i/k if i < k else 1.001+(i-k)/(10000-k)])
        cmd = [sys.executable, str(ROOT / "scripts/experimental/align_buy_line.py"), str(p / "current.csv"),
               str(p / "next.csv"), "--base-line", "1", "--base-panel", str(panel), "--panel", str(panel)]
        result["alignment_drift_reproducer"] = {
            "registered_share_pct": 17.77, "current_share_pct": 17.93, "next_share_pct": 18.09,
            "default_cli": subprocess.check_output(cmd, text=True),
            "explicit_registered_share_cli": subprocess.check_output(cmd + ["--registered-share", "17.77"], text=True)}
    (EXP / "review_evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "alignment_drift_reproducer"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Freeze the buy-line grid, verify production equivalence, and measure eligibility."""
import bisect
from collections import Counter
import contextlib
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shlex
import sys
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
WCEXP = EXP.parent / "exp_oi168_wc_20260909"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import sweep_backtest_configs as sw
import screen_daily_volume_price_signals as daily
from align_buy_line import load_spans, ratios


def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fingerprint(paths):
    result = {}
    for p in sorted(paths):
        h = hashlib.sha256()
        with p.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""): h.update(block)
        result[str(p.relative_to(ROOT))] = {"bytes": p.stat().st_size, "sha256": h.hexdigest()}
    return result


def digest(path, codes=None):
    h = hashlib.sha256(); n = 0
    with path.open(newline="") as f:
        reader = csv.reader(f); header = next(reader); i = header.index("security_code")
        h.update((",".join(header) + "\n").encode())
        for row in reader:
            if codes is None or row[i] in codes:
                h.update((",".join(row) + "\n").encode()); n += 1
    return {"sha256": h.hexdigest(), "rows": n}


def main():
    args = shlex.split(sw.BASE)
    base_paths = {k: ROOT / args[args.index(k)+1] for k in ("--daily-states", "--hold-states", "--universe-file")}
    base_line = 1 - float(args[args.index("--width")+1])
    assert base_line == 1.0454 and args[args.index("--swap-margin")+1] == "0.15"
    panel = base_paths["--universe-file"]
    panel_codes = set(load_spans(panel))
    codes = set((WCEXP / "codes.txt").read_text().split())
    assert panel_codes <= codes
    states = WCEXP / "val/WCOP/states_base.csv"
    hold = WCEXP / "val/WCOP/states_hold.csv"
    state_args = f"--daily-states {states.relative_to(ROOT)} --hold-states {hold.relative_to(ROOT)}"
    lines = sorted({Decimal(x) for x in [".50", ".60", ".70", ".75", ".80", ".85", "1.25", "1.30", "1.40", "1.50", "1.75", "2", "3", "1.0414"]}
                   | {Decimal(i)/100 for i in range(90, 121)})
    grid = [{"arm": "BASE", "buy_line": base_line, "diagnostic": False}]
    grid += [{"arm": f"BL{int(v*10000):05d}OP09", "buy_line": float(v), "diagnostic": False} for v in lines]
    grid += [{"arm": "BLNONEOP09", "buy_line": 1e9, "diagnostic": True}]
    assert len(grid) == 47
    save("grid.json", grid)
    (EXP / "configs.txt").write_text("\n".join(
        f"{r['arm']}|{state_args} --width {1-r['buy_line']:.4f}" for r in grid) + "\n")
    with (ROOT / "data/backtest/scan_summaries.csv").open() as f:
        tags = {sw.summary_tag("BASE", start, suffix) for start in sw.DEFAULT_STARTS for suffix in ("", "fixed")}
        registered = [r for r in csv.DictReader(f) if r["扫描标签"] in tags]
    assert len(registered) == 28
    with (EXP / "baseline_before.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(registered[0]), lineterminator="\n"); w.writeheader(); w.writerows(registered)

    sources = set(base_paths.values()) | {states, hold, WCEXP / "codes.txt"}
    ends = Counter()
    for code in panel_codes:
        path = ROOT / f"data/raw/ohlcv/{code}.csv"; sources.add(path)
        with path.open("rb") as f:
            header = f.readline().decode("utf-8-sig").strip().split(",")
            f.seek(0, 2); f.seek(max(0, f.tell()-4096)); row = next(csv.reader(f.read().decode().splitlines()[-1:]))
        ends[row[header.index("date")]] += 1
    for folder in ("data/raw/financials", "data/raw/financials_statements"):
        sources.update((ROOT / folder).rglob("*.csv"))
    sources.update((ROOT / "scripts").glob("*.py"))
    for name in ("data/raw/ohlcv/INDEX_000001.csv", "data/raw/corporate_actions/a_share_corporate_actions.csv",
                 "data/raw/a_share_delisted_roster.csv", "data/raw/a_share_securities.csv", "data/reference/cost_of_equity_inputs.csv",
                 "data/reference/consolidation_events.csv", "data/processed/entity_reset_dates.csv", "data/interim/statement_restatements.csv",
                 "data/processed/a_share_pool_model_bands_adopted.csv", "data/processed/daily_buy_candidates.csv",
                 "scripts/experimental/align_buy_line.py", "docs/000_Ashare_workflow.md"):
        sources.add(ROOT / name)
    sources |= {EXP / n for n in ("prepare.py", "run.py", "scan.py", "preregister.md", "configs.txt", "grid.json", "baseline_before.csv")}
    before = fingerprint(sources)
    previous = json.loads((WCEXP / "manifest.json").read_text())["inputs"]
    for path, value in previous.items():
        if path.startswith(("data/raw/", "data/reference/")) and path in before:
            assert before[path] == value, f"Unexpected change since operating valuation build: {path}"
    save("manifest.json", {"started_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "job_id": os.environ.get("SLURM_JOB_ID"), "base": sw.BASE, "starts": sw.DEFAULT_STARTS,
        "metric": sw.METRIC_VERSION, "inputs": before, "panel_codes": len(panel_codes),
        "price_ends": dict(sorted(ends.items())), "candidate_count": len(grid)-1})
    eq = []
    for subset, production in ((states, base_paths["--daily-states"]), (hold, base_paths["--hold-states"])):
        a, b = digest(subset), digest(production, codes)
        eq.append({"side": subset.name, "subset": a, "production": b, "equal": a == b})
        assert a == b, f"Production/subset mismatch: {subset}"
    save("production_equivalence.json", eq)
    observations = ratios(states, load_spans(panel))
    assert observations and all(math.isfinite(v) for v in observations) and max(observations) < 1e9
    with (ROOT / "data/processed/daily_buy_candidates.csv").open() as f: latest = list(csv.DictReader(f))
    with contextlib.redirect_stdout(io.StringIO()):
        bands = daily.load_model_bands(ROOT / "data/processed/a_share_pool_model_bands_adopted.csv", "2026-09-10")
        daily.attach_model_pv(latest, bands, "2026-09-09", None)
    eligibility = []
    for r in grid:
        line = r["buy_line"]; current = 0; trend = 0
        for stock in latest:
            pv, close, ma20, ma60 = (daily.to_float(stock[k]) for k in ("model_pv", "close", "ma20", "ma60"))
            if pv is not None and pv <= line:
                current += 1
                if (all(v is not None for v in (close, ma20, ma60)) and close > ma20 > ma60
                    and stock["signal_state"] == "ok" and stock["review_frozen"] == "False"):
                    trend += 1
        count = bisect.bisect_right(observations, line)
        eligibility.append({**r, "observations": len(observations), "eligible_company_days": count,
                            "eligible_share": count/len(observations), "current_value_eligible": current,
                            "current_value_trend_eligible": trend})
    with (EXP / "eligibility.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(eligibility[0]), lineterminator="\n"); w.writeheader(); w.writerows(eligibility)
    unchanged = fingerprint(sources) == before
    save("prepare_verification.json", {"inputs_unchanged": unchanged, "equivalence": eq,
        "maximum_observed_pv": max(observations), "configurations": len(grid)})
    assert unchanged
    print("PREPARE COMPLETE: 47 configurations, production equivalence verified.", flush=True)


if __name__ == "__main__": main()

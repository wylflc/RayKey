#!/usr/bin/env python3
"""Reproduce OI-175's two-company replay; --apply updates only affected current rows.

Run from the repository root. Large derived states are streamed, never loaded in
memory. Existing historical rows outside the disclosed event are preserved.
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import minority_claims as mc

OUT = ROOT / "data/interim/oi175_20260910"
FLAGS = ["--codes", "000938,300919", "--value-model", "roic", "--roe-source", "onesided_max",
         "--roe-lift", "2.0", "--uniform-tier", "L2", "--since", "2002-01-01",
         "--roic-nopat-source", "conditional3", "--roic-growth", "hybrid", "--roic-cycle-guard", "peak",
         "--roic-cond-detect", "graded", "--roic-peak-ramp", "0.3", "--ttm-current", "on",
         "--growth-damp", "on", "--thin-equity-max", "0.5", "--roic-trail-weight", "0",
         "--minority-basis", "earnings", "--wc-aggregation", "operating", "--statements-dir",
         str(ROOT / "data/interim/company_review_20260910/statements")]


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def key(r):
    return r["security_code"], r["report_date"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for suffix, extra in (("", []), ("_b2", ["--ttm-trust", "on", "--ttm-trust-delta", "0.02"])):
        cmd = [sys.executable, str(ROOT / "scripts/build_historical_valuation_bands.py"), *FLAGS, *extra,
               "--out-bands", str(OUT / f"roic_bands{suffix}.csv"),
               "--out-daily", f"/tmp/oi175_roic_daily{suffix}.csv"]
        with (OUT / f"build{suffix}.log").open("w") as log:
            subprocess.run(cmd, cwd=ROOT, stdout=log, check=True)

    fields, old = read(ROOT / "data/interim/company_review_20260910/roic_bands.csv")
    new = {key(r): r for r in read(OUT / "roic_bands.csv")[1]}
    changed = [key(r) for r in old if any(r[c] != new[key(r)][c] for c in fields)]
    assert all(c == "000938" and p >= "2024-09-30" for c, p in changed), changed
    assert len(changed) == 8
    memberships = [r for r in read(ROOT / "data/processed/pit_attention/panel_moat_bank_v6b.csv")[1]
                   if r["security_code"] == "000938"]
    assert not memberships, "Affected stock is in BASE universe: full path comparison required"
    summary = dict(changed_base_periods=changed, zhongwei_unchanged_periods=31,
                   ziguang_pre_event_unchanged_periods=90, base_universe_memberships=memberships,
                   last_price_date="2026-08-07", current_files=[])
    for suffix in ("", "_b2"):
        rows = read(OUT / f"roic_bands{suffix}.csv")[1]
        latest = next(r for r in rows if key(r) == ("000938", "2026-06-30"))
        assert mc.row_blocked(latest) and not latest["intrinsic_value"]
        usable, blocked = __import__("apply_model_bands_to_dossiers").latest_model_bands(
            OUT / f"roic_bands{suffix}.csv", "2025-01-01", as_of="2026-09-10")
        assert "000938" not in usable and mc.row_blocked(blocked["000938"])
        if not args.apply:
            continue
        replacement = {key(r): r for r in rows if mc.row_blocked(r)}
        path = ROOT / f"data/processed/roic_bands{suffix}.csv"
        tmp = path.with_suffix(".oi175_tmp")
        count = 0
        with path.open(encoding="utf-8-sig", newline="") as f, tmp.open("w", encoding="utf-8-sig", newline="") as out:
            reader = csv.DictReader(f)
            header = list(dict.fromkeys([*reader.fieldnames, *mc.ROW_FIELDS]))
            writer = csv.DictWriter(out, fieldnames=header)
            writer.writeheader()
            for r in reader:
                if key(r) in replacement:
                    r = replacement.pop(key(r)); count += 1
                writer.writerow(r)
            assert not replacement, "Missing existing model rows"
        tmp.replace(path)
        summary["current_files"].append(dict(path=str(path.relative_to(ROOT)), replaced_rows=count,
                                              all_other_existing_fields_unchanged=True))

    if args.apply:
        for filename in ("roic_daily_raw.csv", "roic_daily_raw_b2.csv", "a_share_daily_states_adopted.csv",
                         "a_share_daily_states_b2.csv", "a_share_daily_states_hold.csv"):
            path = ROOT / "data/processed" / filename
            tmp = path.with_suffix(".oi175_tmp")
            kept_hash = hashlib.sha256()
            removed = count = 0
            first_removed = last_removed = ""
            with path.open("rb") as f, tmp.open("wb") as out:
                header = f.readline(); out.write(header); kept_hash.update(header)
                assert header.startswith(b"security_code,date,"), header
                for line in f:
                    count += 1
                    if line.startswith(b"000938,"):
                        day = line.split(b",", 2)[1].decode()
                        if mc.blocking_reason("000938", day, ""):
                            removed += 1
                            first_removed = first_removed or day
                            last_removed = day
                            continue
                    out.write(line); kept_hash.update(line)
            # Verify the newly written bytes equal precisely the retained old stream.
            with tmp.open("rb") as f:
                actual = hashlib.file_digest(f, "sha256").hexdigest()
            assert actual == kept_hash.hexdigest()
            tmp.replace(path)
            summary["current_files"].append(dict(path=str(path.relative_to(ROOT)), rows_before=count,
                                                  rows_removed=removed, first_removed=first_removed,
                                                  last_removed=last_removed, kept_sha256=actual))
            print(filename, "removed", removed, flush=True)
        landing = OUT / "landing_validation.json"
        if landing.exists():
            landing = OUT / "repeat_application_validation.json"
        landing.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
    else:
        (OUT / "replay_validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
    print("PASS: event-only differences, both valuation paths blocked, unaffected replay identical")


if __name__ == "__main__":
    main()

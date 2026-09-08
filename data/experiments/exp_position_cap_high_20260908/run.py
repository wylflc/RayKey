"""Run preregistered high caps with the existing strict guard and formal scanner."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
PREVIOUS = EXP.with_name("exp_position_cap_25_20260908")
spec = importlib.util.spec_from_file_location("cap25_common", PREVIOUS / "run.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
common.EXP = EXP
sw = common.sw
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import ex_winner_symmetry as symmetry

CONTROL = "PC60SSEP08"
CANDIDATES = [f"PC{cap}SSEP08" for cap in (70, 80, 90, 100)]
LABELS = ["BASE", CONTROL, *CANDIDATES]


def scan(config, group, workers, exclude=None):
    output = EXP / f"sweep_{group}.txt"
    report = EXP / f"report_{group}.txt"
    command = [sys.executable, str(PREVIOUS / "strict_scan.py"), str(EXP / config),
               "--out", str(output), "--workers", str(workers),
               "--title", "单股买入上限放宽：严格60%／70%／80%／90%／100%与当前BASE"]
    if exclude:
        command += ["--exclude-codes", ",".join(exclude)]
    with report.open("w", encoding="utf-8") as handle:
        subprocess.run(command, stdout=handle, cwd=ROOT, check=True)
    report.write_text("\n".join(line.rstrip() for line in report.read_text().splitlines()) + "\n")
    rows = [line for line in output.read_text().splitlines() if line and not line.startswith("#")]
    assert all(not line.endswith(("|ERR", "|EMPTY")) for line in rows), "Failed scan paths"
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=56)
    parser.add_argument("--resume-full-a", action="store_true")
    args = parser.parse_args()
    assert args.workers <= int(os.environ.get("SLURM_CPUS_PER_TASK", args.workers))
    previous = json.loads((PREVIOUS / "manifest.json").read_text())
    old_files = {ROOT / path for path in previous["inputs"]}
    assert common.fingerprint(old_files) == previous["inputs"], "Previous experiment inputs changed"
    assert sw.BASE == previous["base"] and sw.DEFAULT_STARTS == previous["starts"]
    assert sw.METRIC_VERSION == previous["metric"] == "m2"
    files = old_files | {EXP / "run.py", EXP / "configs.txt", EXP / "preregister.md",
                         PREVIOUS / "run.py", PREVIOUS / "strict_scan.py",
                         PREVIOUS / "strict_cap_engine.py", PREVIOUS / "summary_rows.csv",
                         ROOT / "scripts/experimental/ex_winner_symmetry.py"}
    inputs = common.fingerprint(files)
    if args.resume_full_a:
        initial = json.loads((EXP / "manifest_initial.json").read_text())
        # Only this orchestration file changed; strategy and registered design did not.
        assert {key:value for key,value in inputs.items() if key != str((EXP / 'run.py').relative_to(ROOT))} == {
            key:value for key,value in initial["inputs"].items() if key != str((EXP / 'run.py').relative_to(ROOT))}
    common.save_json("manifest.json", {
        "started_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "job_id": os.environ.get("SLURM_JOB_ID"), "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "base": sw.BASE, "starts": sw.DEFAULT_STARTS, "metric": sw.METRIC_VERSION,
        "price_ends": previous["price_ends"], "previous_input_hashes_match": True,
        "new_candidate_arms": CANDIDATES, "inputs": inputs,
        "resumed_full_A": args.resume_full_a,
    })
    with (PREVIOUS / "summary_rows.csv").open() as handle:
        previous_rows = {(row["group"], row["arm"], row["start"]):
                         {key: value for key, value in row.items() if key not in ("group", "arm", "start")}
                         for row in csv.DictReader(handle)}
    full_paths = (len([line for line in (EXP / "sweep_full_A.txt").read_text().splitlines()
                       if line and not line.startswith("#")]) if args.resume_full_a
                  else scan("configs.txt", "full_A", args.workers))
    assert full_paths == len(LABELS) * len(sw.DEFAULT_STARTS) * 2
    if args.resume_full_a:
        groups = {}
        for group in ("full", "A"):
            groups[group] = {}
            for label in LABELS:
                groups[group][label] = []
                for start in sw.DEFAULT_STARTS:
                    path = EXP / "summaries" / group / f"summary_{sw.summary_tag(label,start,'fixed' if group=='A' else '')}.csv"
                    with path.open() as handle:
                        groups[group][label].append(next(csv.DictReader(handle)))
    else:
        groups = {"full": common.snapshot(LABELS, "full", False),
                  "A": common.snapshot(LABELS, "A", True)}
    baseline_checks, diagnostic_roundoff = [], []
    for group in ("full", "A"):
        for label in ("BASE", CONTROL):
            for start, row in zip(sw.DEFAULT_STARTS, groups[group][label]):
                old = previous_rows[("strict_" + group, label, start.replace("-", ""))]
                for key in set(row) | set(old):
                    if row.get(key) == old.get(key):
                        continue
                    assert key == "前五赢家占正贡献" and abs(float(row[key])-float(old[key])) <= 1e-14, (group,label,start,key)
                    diagnostic_roundoff.append({"group":group,"arm":label,"start":start,"field":key,"previous":old[key],"current":row[key]})
            baseline_checks.append(f"{group}:{label}:all_report_fields_identical")
    a = sorted(symmetry.top5("BASE", sw.EX5_ANCHOR_START))
    selections, unions = {}, {}
    for candidate in CANDIDATES:
        b = sorted(symmetry.top5(candidate, sw.EX5_ANCHOR_START))
        union = tuple(sorted(set(a) | set(b)))
        unions.setdefault(union, []).append(candidate)
        selections[candidate] = {"A": a, "B": b, "U": list(union)}
    common.save_json("winner_sets.json", selections)
    extras = dict(line.split("|", 1) for line in (EXP / "configs.txt").read_text().splitlines() if line)
    union_paths, union_groups = 0, {}
    try:
        for index, (codes, candidates) in enumerate(unions.items(), 1):
            name = f"U{index}"
            labels = ["BASE", CONTROL, *candidates]
            reused = list(codes) == a
            if reused:
                groups[name] = {label: groups["A"][label] for label in labels}
                (EXP / f"report_{name}.txt").write_text("U=A；复用 report_full_A.txt 中相同臂的 A 表。\n")
            else:
                config = f"configs_{name}.txt"
                (EXP / config).write_text("\n".join(f"{label}|{extras[label]}" for label in labels) + "\n")
                count = scan(config, name, args.workers, list(codes))
                assert count == len(labels) * len(sw.DEFAULT_STARTS)
                union_paths += count
                groups[name] = common.snapshot(labels, name, True)
            union_groups[name] = {"codes": list(codes), "candidates": candidates, "labels": labels, "reuses_A": reused}
    finally:
        # Fixed U runs share global EX5 labels with A; restore their correct meaning.
        for group in ("full", "A"):
            for path in (EXP / "summaries" / group).glob("summary_*.csv"):
                shutil.copyfile(path, sw.OUT_DIR / path.name)
    consolidated = [{"group": group, "arm": label, "start": start, **row}
                    for group, arms in groups.items() for label, rows in arms.items()
                    for start, row in zip(sw.DEFAULT_STARTS, rows)]
    with (EXP / "summary_rows.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(consolidated[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(consolidated)
    unchanged = common.fingerprint(files) == inputs
    common.save_json("verification.json", {
        "completed_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "inputs_unchanged": unchanged, "baseline_checks": baseline_checks,
        "diagnostic_roundoff": diagnostic_roundoff,
        "paths_full_A": full_paths, "paths_U": union_paths, "summary_rows": len(consolidated),
        "union_groups": union_groups, "ordinary_A_summary_cache_restored": True,
        "strict_wrapper": str((PREVIOUS / "strict_cap_engine.py").relative_to(ROOT)),
        "union_config_hashes": common.fingerprint(set(EXP.glob("configs_U*.txt"))),
    })
    assert unchanged
    print(f"Complete: {full_paths + union_paths} executed paths; {len(consolidated)} exact summary rows")


if __name__ == "__main__":
    main()

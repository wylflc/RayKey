"""Verify exact cap semantics separately, preserving the original BASE as control."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import run as common

EXP, ROOT, sw = common.EXP, common.ROOT, common.sw


def scan(config, output, report, workers, exclude=None):
    command = [sys.executable, str(EXP / "strict_scan.py"), str(EXP / config),
               "--out", str(EXP / output), "--workers", str(workers),
               "--title", "单股买入上限：整手严格守卫核验（BASE 保留原实现）"]
    if exclude:
        command += ["--exclude-codes", ",".join(exclude)]
    with (EXP / report).open("w") as handle:
        subprocess.run(command, stdout=handle, cwd=ROOT, check=True)
    rows = [line for line in (EXP / output).read_text().splitlines() if line and not line.startswith("#")]
    assert all(not line.endswith(("|ERR", "|EMPTY")) for line in rows)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=56)
    args = parser.parse_args()
    prior = json.loads((EXP / "manifest.json").read_text())
    files = {ROOT / path for path in prior["inputs"]}
    assert common.fingerprint(files) == prior["inputs"], "Original experiment inputs changed"
    labels = ["BASE", "PC60SSEP08", "PC20SSEP08", "PC25SSEP08", "PC30SSEP08"]
    started = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    rows = scan("configs_strict.txt", "sweep_strict_full_A.txt", "report_strict_full_A.txt", args.workers)
    assert len(rows) == len(labels) * len(sw.DEFAULT_STARTS) * 2
    full = common.snapshot(labels, "strict_full", False)
    a_rows = common.snapshot(labels, "strict_A", True)
    anchor = sw.DEFAULT_STARTS.index(sw.EX5_ANCHOR_START)
    a = set(full["BASE"][anchor]["前五赢家"].split("/"))
    b = set(full["PC25SSEP08"][anchor]["前五赢家"].split("/"))
    u = sorted(a | b)
    if u == sorted(a):
        (EXP / "report_strict_U.txt").write_text("U=A，复用 report_strict_full_A.txt 中对应两臂。\n")
        u_paths = 0
    else:
        u_rows = scan("configs_strict_U.txt", "sweep_strict_U.txt", "report_strict_U.txt", args.workers, u)
        assert len(u_rows) == 2 * len(sw.DEFAULT_STARTS)
        common.snapshot(["BASE", "PC25SSEP08"], "strict_U", True)
        u_paths = len(u_rows)
    unchanged = common.fingerprint(files) == prior["inputs"]
    diagnostics = [json.loads(path.read_text()) for path in sorted((EXP / "strict_guard_events").glob("*.json"))]
    common.save_json("verification_strict.json", {
        "started_beijing": started, "completed_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "inputs_unchanged": unchanged, "paths_full_A": len(rows), "paths_U": u_paths,
        "A": sorted(a), "B": sorted(b), "U": u, "U_reuses_A": u == sorted(a),
        "guard_events": {row["label"]: row["guarded_buy_opportunities"] for row in diagnostics},
        "wrapper_hashes": common.fingerprint({EXP / "strict_cap_engine.py", EXP / "strict_scan.py", EXP / "configs_strict.txt"}),
    })
    assert unchanged
    print(f"Complete: {len(rows) + u_paths} paths; strict cap guard diagnostics {len(diagnostics)}")


if __name__ == "__main__":
    main()

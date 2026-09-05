#!/usr/bin/env python3
"""Fixed RF5 cost stress and endpoint sensitivity; no re-selection across scenarios."""
import concurrent.futures
from contextlib import redirect_stdout
import csv
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep


def main():
    exp = ROOT / "data/experiments/exp_whipsaw_joint"
    rf = "--swap-chop-mode repeat-flat --swap-chop-cooldown 5"
    fixed = "601088,002128,000933,000651,000338"
    scenarios = {f"slip{bp}": [("BASE", f"--slippage-bp {bp} --until 2026-08-28"),
                              ("WJ_RF5", rf + f" --slippage-bp {bp} --until 2026-08-28")]
                 for bp in (0, 10, 20, 30)}
    scenarios["trunc2024"] = [("BASE", "--until 2024-12-31"),
                              ("WJ_RF5", rf + " --until 2024-12-31"),
                              ("WJ_R5", "--swap-chop-mode repeat --swap-chop-cooldown 5 --until 2024-12-31")]
    (exp / "validation_manifest.json").write_text(json.dumps(dict(scenarios=scenarios, excluded=fixed), indent=2))
    sweep.OUT_DIR = exp / "validation_raw"
    sweep.OUT_DIR.mkdir(exist_ok=True)
    jobs = []
    for scenario, arms in scenarios.items():
        for label, extra in arms:
            for excluded in ("", fixed):
                for start in sweep.DEFAULT_STARTS:
                    tag = "WV" + scenario + label.replace("_", "")
                    jobs.append((scenario, label, (tag, extra, start, excluded)))
    streams = {}
    try:
        for name in scenarios:
            fh = (exp / f"sweep_{name}.txt").open("w")
            fh.write(sweep.metric_header() + "\n" + f"#EX5|fixed|{fixed}\n")
            streams[name] = fh
        def one(job):
            scenario, label, task = job
            result = sweep.run_one(task)
            if len(result.split("|")) != 2 + len(sweep.FIELDS):
                raise RuntimeError(result)
            return scenario, (sweep.EX5_PREFIX if task[3] else "") + label + "|" + result.split("|", 1)[1]
        with concurrent.futures.ThreadPoolExecutor(max_workers=60) as pool:
            for n, (scenario, line) in enumerate(pool.map(one, jobs), 1):
                streams[scenario].write(line + "\n")
                streams[scenario].flush()
                if n % 28 == 0:
                    print(f"{n}/{len(jobs)}", flush=True)
    finally:
        for fh in streams.values():
            fh.close()
    for scenario in scenarios:
        with (exp / f"report_{scenario}.txt").open("w") as out, redirect_stdout(out):
            sweep.report(exp / f"sweep_{scenario}.txt", f"RF5固定验证：{scenario}")
    destination = exp / "summaries" / "validation"
    destination.mkdir(parents=True, exist_ok=True)
    for source in sweep.OUT_DIR.glob("summary_*.csv"):
        shutil.copyfile(source, destination / source.name.replace("summary_", "summary_WJval20260906_", 1))


if __name__ == "__main__":
    main()

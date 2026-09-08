"""Reproduce the preregistered cap comparison using the formal scanner."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sw


def read_summary(label, start, excluded=False):
    path = sw.OUT_DIR / f"summary_{sw.summary_tag(label, start, 'fixed' if excluded else '')}.csv"
    with path.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["计量版本"] == sw.METRIC_VERSION
    assert row["首个净值日"] >= start
    return path, row


def fingerprint(paths):
    result = {}
    for path in sorted(paths):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result[str(path.relative_to(ROOT))] = {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}
    return result


def save_json(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scan(config, sweep, report, workers, exclude=None):
    command = [sys.executable, "scripts/sweep_backtest_configs.py", str(EXP / config),
               "--out", str(EXP / sweep), "--workers", str(workers),
               "--title", "单股买入上限敏感度：60% 对照 20%／25%／30%"]
    if exclude:
        command += ["--exclude-codes", ",".join(exclude)]
    with (EXP / report).open("w", encoding="utf-8") as handle:
        subprocess.run(command, cwd=ROOT, stdout=handle, check=True)
    lines = (EXP / sweep).read_text().splitlines()
    data = [line for line in lines if line and not line.startswith("#")]
    assert all(not line.endswith(("|ERR", "|EMPTY")) for line in data), "Failed scan paths"
    return data


def snapshot(labels, group, excluded):
    directory = EXP / "summaries" / group
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for label in labels:
        result[label] = []
        for start in sw.DEFAULT_STARTS:
            path, row = read_summary(label, start, excluded)
            shutil.copyfile(path, directory / path.name)
            result[label].append(row)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=56)
    args = parser.parse_args()
    assert args.workers <= int(os.environ.get("SLURM_CPUS_PER_TASK", args.workers))
    base_args = shlex.split(sw.BASE)
    inputs = {ROOT / base_args[base_args.index(option) + 1]
              for option in ("--daily-states", "--hold-states", "--universe-file")}
    panel = ROOT / base_args[base_args.index("--universe-file") + 1]
    with panel.open() as handle:
        codes = {row["security_code"] for row in csv.DictReader(handle)}
    ends = Counter()
    for code in sorted(codes):
        path = ROOT / "data/raw/ohlcv" / f"{code}.csv"
        assert path.exists(), path
        inputs.add(path)
        with path.open("rb") as handle:
            fields = handle.readline().decode("utf-8-sig").strip().split(",")
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 4096))
            last = next(csv.reader(handle.read().decode().splitlines()[-1:]))
        ends[last[fields.index("date")]] += 1
    for relative in ("scripts/backtest_valuation_strategy.py", "scripts/sweep_backtest_configs.py",
                     "data/raw/corporate_actions/a_share_corporate_actions.csv",
                     "data/raw/a_share_delisted_roster.csv", "data/reference/cost_of_equity_inputs.csv",
                     "data/experiments/exp_position_cap_25_20260908/configs.txt",
                     "data/experiments/exp_position_cap_25_20260908/configs_U.txt"):
        inputs.add(ROOT / relative)
    original = fingerprint(inputs)
    manifest = {"started_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                "base": sw.BASE, "starts": sw.DEFAULT_STARTS, "metric": sw.METRIC_VERSION,
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "job_id": os.environ.get("SLURM_JOB_ID"), "price_ends": dict(sorted(ends.items())),
                "inputs": original, "new_candidate_arms": 3}
    save_json("manifest.json", manifest)
    old = {start: read_summary("BASE", start)[1] for start in sw.DEFAULT_STARTS}
    labels = ["BASE", "PC20SEP08", "PC25SEP08", "PC30SEP08"]
    main_rows = scan("configs.txt", "sweep_full_A.txt", "report_full_A.txt", args.workers)
    assert len(main_rows) == len(labels) * len(sw.DEFAULT_STARTS) * 2
    groups = {"full": snapshot(labels, "full", False), "A": snapshot(labels, "A", True)}
    anchor = sw.DEFAULT_STARTS.index(sw.EX5_ANCHOR_START)
    a = set(groups["full"]["BASE"][anchor]["前五赢家"].split("/"))
    b = set(groups["full"]["PC25SEP08"][anchor]["前五赢家"].split("/"))
    union = sorted(a | b)
    if union == sorted(a):
        groups["U"] = {label: groups["A"][label] for label in ("BASE", "PC25SEP08")}
        (EXP / "report_U.txt").write_text("U=A，复用 report_full_A.txt 的 A 集对应两臂；未重复运行。\n")
        union_paths = 0
    else:
        union_rows = scan("configs_U.txt", "sweep_U.txt", "report_U.txt", args.workers, union)
        assert len(union_rows) == 2 * len(sw.DEFAULT_STARTS)
        groups["U"] = snapshot(["BASE", "PC25SEP08"], "U", True)
        union_paths = len(union_rows)
    comparisons = []
    keys = ["年化", "滚动5年年化中位", "滚动5年年化P25", "互不重叠5年块中位",
            "逐年收益中位", "逐年最差", "最大回撤", "滚动5年回撤中位", "Sharpe", "Calmar",
            "平均仓位", "持仓数中位", "年均换手", "单票权重中位", "前三权重中位"]
    for group, arms in groups.items():
        for label, rows in arms.items():
            for key in keys:
                values = [float(row[key]) for row in rows]
                diffs = [value - float(base[key]) for value, base in zip(values, arms["BASE"])]
                comparisons.append({"group": group, "arm": label, "metric": key,
                                    "median": statistics.median(values),
                                    "paired_delta_median": statistics.median(diffs),
                                    "positive_starts": sum(delta > 0 for delta in diffs), "starts": len(values)})
    with (EXP / "comparisons.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    # Compare the previous registered baseline without assuming every field is numeric.
    diffs = []
    for start, row in zip(sw.DEFAULT_STARTS, groups["full"]["BASE"]):
        for key in sw.FIELDS:
            if row.get(key, "") != old[start].get(key, ""):
                diffs.append({"start": start, "field": key, "before": old[start].get(key), "after": row.get(key)})
    verification = {"inputs_unchanged": original == fingerprint(inputs), "paths_full_A": len(main_rows),
                    "paths_U": union_paths, "A": sorted(a), "B": sorted(b), "U": union,
                    "U_reuses_A": union == sorted(a), "baseline_field_changes": diffs,
                    "completed_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}
    save_json("verification.json", verification)
    assert verification["inputs_unchanged"], "Inputs changed during experiment"
    print(json.dumps({key: value for key, value in verification.items() if key != "baseline_field_changes"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Preregistered cutoff, symmetric winner exclusions, dose and attribution checks."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import csv
import json
import shlex
import statistics
import sys

from trough_guard_review import EXP, ROOT, configs, report, run_log, save_json, sha
import sweep_backtest_configs as sweep
from sb1_daily_buys_checks import run_pass, top5
from dose_table import load, paired, verdict
from delta_attribution import load_contrib
from ex_winner_symmetry_report import CLAUSE4


def complete(path, labels):
    """Reuse only complete double tables from this isolated, manifest-checked run."""
    if not path.exists():
        return False
    full, ex, _ = load(path)
    return all(set(group) == set(labels) and all(set(v) == set(sweep.DEFAULT_STARTS)
                                               for v in group.values()) for group in (full, ex))


def input_stamp():
    manifest = json.loads((EXP / "manifest.json").read_text())
    return {"main_sweep_sha256": sha(EXP / "sweep.txt"),
            **{k: manifest[k] for k in ("base", "engine_sha256", "panel_sha256", "rebuilt_states_sha256", "starts")}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=60)
    args = ap.parse_args()
    original = EXP / "summaries"
    full, ex, labels = load(EXP / "sweep.txt")
    registered = dict(configs())
    stamp = input_stamp()
    stamp_path = EXP / "checks_inputs.json"
    if stamp_path.exists():
        assert json.loads(stamp_path.read_text()) == stamp, "inputs changed; do not reuse prior stress tests"
    else:
        assert not (EXP / "sweep_cutoff.txt").exists(), "existing checks have no input stamp; audit before reuse"
        save_json("checks_inputs.json", stamp)
    # Formal BASE was run on full-market files and matched this subset in 28 paths.
    # Subsequent read-only stress tests can therefore use the verified subset too.
    arms = [(l, registered["REBUILT_CHECK"] if l == "BASE" else e)
            for l, e in registered.items() if l != "REBUILT_CHECK"]
    a = top5(original, "BASE")
    # All preregistered doses get a fixed common cutoff; keep the main-snapshot A.
    sweep.OUT_DIR = EXP / "cutoff_summaries"
    sweep.OUT_DIR.mkdir(exist_ok=True)
    cutoff_arms = [(l, e + f" --out-dir {sweep.OUT_DIR} --until 2026-08-07") for l, e in arms]
    print(f"Common cutoff: {len(cutoff_arms) * 28} paths", flush=True)
    if not complete(EXP / "sweep_cutoff.txt", [l for l, _ in cutoff_arms]):
        with (EXP / "sweep_cutoff.txt").open("w", encoding="utf-8") as out:
            run_pass(cutoff_arms, "", args.workers, out)
            out.write(f"#EX5|{sweep.EX5_ANCHOR_START}|{','.join(sorted(a))}\n")
            run_pass(cutoff_arms, ",".join(sorted(a)), args.workers, out)
    else:
        print("Reusing complete cutoff tables", flush=True)
    report(EXP / "sweep_cutoff.txt", "report_cutoff.txt", "统一截止2026-08-07（A固定为主快照相对贡献前五）")

    selected = {"OFF", "OFF_BUY1", "OFF_BUY3", "OFF_BUY5"}
    selected.update(l for l in labels if l.startswith("OFF") and l != "OFF_FIXEDLINE"
                    and not verdict(full, ex, l).startswith("不采纳"))
    sets = {}
    source_lines = (EXP / "sweep.txt").read_text().splitlines()
    for label in sorted(selected):
        b = top5(original, label)
        union = a | b
        sets[label] = {"A": sorted(a), "B": sorted(b), "U": sorted(union)}
        sweep.OUT_DIR = EXP / "union_summaries" / label
        sweep.OUT_DIR.mkdir(parents=True, exist_ok=True)
        chosen = [(l, e + f" --out-dir {sweep.OUT_DIR}") for l, e in arms if l in ("BASE", label)]
        path = EXP / f"sweep_union_{label}.txt"
        if not complete(path, ("BASE", label)):
            with path.open("w", encoding="utf-8") as out:
                for line in source_lines:
                    if line.split("|", 1)[0] in ("BASE", label):
                        out.write(line + "\n")
                out.write(f"#EX5|{sweep.EX5_ANCHOR_START}|{','.join(sorted(union))}\n")
                if union == a:
                    for line in source_lines:
                        if line.split("|", 1)[0] in ("EX5:BASE", "EX5:" + label):
                            out.write(line + "\n")
                else:
                    print(f"Union {label}: {len(union)} codes", flush=True)
                    run_pass(chosen, ",".join(sorted(union)), args.workers, out)
        else:
            print(f"Reusing complete union {label}", flush=True)
        report(path, f"report_union_{label}.txt", f"{label}：赢家并集U对照")
        _, u, _ = load(path)
        bad = {key: paired(u, label, key)[0] * scale * good for key, scale, good in CLAUSE4
               if paired(u, label, key)[0] * scale * good < -0.15}
        sets[label]["clause4_bad"] = bad
        sets[label]["clause4_pass"] = len(bad) <= 1 and all(v >= -1 for v in bad.values())
    save_json("union_sets.json", sets)

    artifacts = EXP / "artifacts"
    base_cycles = next(artifacts.glob("*_trough_BASE_trades.csv"))
    pnl, relative = load_contrib(base_cycles)
    assert relative, "must not silently fall back to nominal PnL"
    ranked = sorted(pnl, key=lambda c: (-pnl[c], c))
    assert set(ranked[:5]) == a
    # Main off and the requested 1/3/5 buy caps, all against identical exclusions.
    dose_labels = {"BASE", "OFF", "OFF_BUY1", "OFF_BUY3", "OFF_BUY5"} | selected
    dose_arms = [(l, e) for l, e in arms if l in dose_labels]
    dose_sets = {}
    for k in (1, 3, 5, 10):
        codes = ranked[:k]
        dose_sets[str(k)] = codes
        sweep.OUT_DIR = EXP / "dose_summaries" / f"K{k}"
        sweep.OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = EXP / f"sweep_k{k}.txt"
        with path.open("w", encoding="utf-8") as out:
            for line in source_lines:
                if line.split("|", 1)[0] in {l for l, _ in dose_arms}:
                    out.write(line + "\n")
            out.write(f"#EX5|{sweep.EX5_ANCHOR_START}|{','.join(codes)}\n")
            if k == 5:
                for line in source_lines:
                    if line.split("|", 1)[0] in {"EX5:" + l for l, _ in dose_arms}:
                        out.write(line + "\n")
            else:
                chosen = [(l, e + f" --out-dir {sweep.OUT_DIR}") for l, e in dose_arms]
                print(f"Winner count K{k}: {len(chosen) * 14} paths", flush=True)
                run_pass(chosen, ",".join(codes), args.workers, out)
        report(path, f"report_k{k}.txt", f"相对贡献赢家前{k}只统一剔除")
    save_json("winner_dose_sets.json", dose_sets)
    for label, extra in arms:
        if label not in selected or list(artifacts.glob(f"*_trough_{label}_trades.csv")):
            continue
        cmd = ([sys.executable, "scripts/backtest_valuation_strategy.py"] + shlex.split(sweep.BASE)
               + shlex.split(extra) + ["--since", "2011-11-01", "--artifacts", "--out-dir", str(artifacts),
                  "--label-suffix", f"_trough_{label}", "--trade-log", str(EXP / f"trades_{label}.csv"),
                  "--candidate-log", str(EXP / f"cands_{label}.csv")])
        run_log(cmd, EXP / f"diag_{label}.txt")
    for label in sorted(selected | {f"OFF_BUY{k}" for k in range(1, 7)}):
        arm_cycles = next(artifacts.glob(f"*_trough_{label}_trades.csv"))
        run_log([sys.executable, "scripts/experimental/delta_attribution.py", "--base", str(base_cycles),
                 "--arm", str(arm_cycles)], EXP / f"attribution_{label}.txt")

    # Machine-readable paired metrics preserve both absolute levels and references.
    rows = []
    for path in sorted(EXP.glob("sweep*.txt")):
        f, e, order = load(path)
        for scope, group in (("full", f), ("excluded", e)):
            for label in order:
                assert len(group[label]) == len(sweep.DEFAULT_STARTS), (path, scope, label)
                refs = ["BASE"] + (["OFF"] if "OFF" in group else [])
                if label.startswith("OFF_BUY") and "ON_BUY" + label[-1] in group:
                    refs += ["ON_BUY" + label[-1]]
                for ref in refs:
                    for key in sweep.FIELDS:
                        delta = [group[label][s][key] - group[ref][s][key] for s in sweep.DEFAULT_STARTS]
                        rows.append(dict(sweep=path.name, sample=scope, arm=label, reference=ref, metric=key,
                                         level=statistics.median(r[key] for r in group[label].values()),
                                         paired_delta=statistics.median(delta), positive=sum(v > 0 for v in delta), n=len(delta)))
    with (EXP / "paired_metrics.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Checks complete: {len(selected)} unions, winner doses, attribution, {len(rows)} metric rows", flush=True)


if __name__ == "__main__":
    main()

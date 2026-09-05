#!/usr/bin/env python3
"""Fresh trough-guard on/off valuation chains and preregistered current-BASE sweep."""
from __future__ import annotations

import argparse
import bisect
import collections
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep
from align_buy_line import load_spans, ratios
from sb1_daily_buys import subset
from sb1_daily_buys_checks import run_pass

EXP = ROOT / "data/experiments/exp_trough_guard_review"
PANEL = ROOT / "data/processed/pit_attention/panel_moat_bank_v6b.csv"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(name, data):
    (EXP / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_log(cmd, log, env=None):
    with log.open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, env=env, check=True)


def prepare():
    EXP.mkdir(parents=True, exist_ok=True)
    with PANEL.open(encoding="utf-8-sig") as fh:
        codes = {r["security_code"].zfill(6) for r in csv.DictReader(fh)}
    codes_file = EXP / "codes.txt"
    codes_file.write_text("\n".join(sorted(codes)) + "\n", encoding="utf-8")
    doc = (ROOT / "docs/000_Ashare_workflow.md").read_text(encoding="utf-8")
    match = re.search(r"# 2\. 构建 ROIC 带与逐日状态\n(.*?)\s+--out-bands", doc, re.S)
    assert match
    common = [t for t in match.group(1).split() if t != "\\"]
    assert common[:2] == ["python3", "scripts/build_historical_valuation_bands.py"]
    common[0] = sys.executable
    common.remove("--all")
    common += ["--codes-file", str(codes_file)]
    divspread = re.search(r"rebuild_bank_bands\.py divspread:([0-9.]+)", doc).group(1)
    manifest = dict(base=sweep.BASE, starts=sweep.DEFAULT_STARTS, build_common=common,
                    divspread=divspread, panel_sha256=sha(PANEL),
                    engine_sha256=sha(ROOT / "scripts/backtest_valuation_strategy.py"), states=[])
    for side, name in (("cand", "adopted"), ("hold", "hold")):
        print(f"Subset production {side}", flush=True)
        manifest["states"].append(subset(ROOT / f"data/processed/a_share_daily_states_{name}.csv",
                                        EXP / f"production_{side}.csv", {c.encode() for c in codes}))
    ends = collections.Counter()
    for code in sorted(codes):
        path = ROOT / f"data/raw/ohlcv/{code}.csv"
        if not path.exists():
            ends["missing"] += 1
            continue
        with path.open("rb") as fh:
            fh.seek(max(0, path.stat().st_size - 4096))
            ends[fh.read().splitlines()[-1].split(b",", 1)[0].decode()] += 1
    manifest["ohlcv_last_dates"] = dict(sorted(ends.items()))
    save_json("manifest.json", manifest)

    def build(job):
        guard, side = job
        out = EXP / guard
        out.mkdir(exist_ok=True)
        raw, bands = out / f"raw_{side}.csv", out / f"bands_{side}.csv"
        cmd = common + ["--trough-guard", guard, "--out-bands", str(bands), "--out-daily", str(raw)]
        if side == "b2":
            cmd += ["--ttm-trust", "on", "--ttm-trust-delta", "0.02"]
        env = dict(os.environ, RK_STMT_GAP_LOG=str(out / f"gaps_{side}.csv"))
        run_log(cmd, out / f"build_{side}.log", env)
        run_log([sys.executable, "scripts/rebuild_bank_bands.py", f"divspread:{divspread}",
                 str(out / f"states_{side}.csv"), str(raw), str(bands)], out / f"bank_{side}.log")
        print(f"Built {guard}/{side}", flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(build, [(g, s) for g in ("on", "off") for s in ("cand", "b2")]))
    for guard in ("on", "off"):
        out = EXP / guard
        run_log([sys.executable, "scripts/build_hold_daily_states.py", "--base", str(out / "states_cand.csv"),
                 "--b2", str(out / "states_b2.csv"), "--out", str(out / "states_hold.csv")], out / "hold.log")
    equivalence = {}
    for side in ("cand", "hold"):
        before, after = sha(EXP / f"production_{side}.csv"), sha(EXP / f"on/states_{side}.csv")
        equivalence[side] = dict(production_subset_sha256=before, fresh_on_sha256=after)
        assert before == after, f"fresh {side} differs from production; inspect before backtesting"
    manifest["fresh_on_equivalence"] = equivalence
    args = shlex.split(sweep.BASE)
    base_line = 1 - float(args[args.index("--width") + 1])
    spans = load_spans(PANEL)
    baseline = ratios(EXP / "on/states_cand.csv", spans)
    off = ratios(EXP / "off/states_cand.csv", spans)
    share = bisect.bisect_right(baseline, base_line) / len(baseline)
    off_line = round(off[min(int(share * len(off)), len(off) - 1)], 4)
    manifest["alignment"] = dict(base_line=base_line, off_line=off_line, base_n=len(baseline), off_n=len(off),
                                 base_share=share, off_share=bisect.bisect_right(off, off_line) / len(off))
    manifest["rebuilt_states_sha256"] = {f"{g}/{s}": sha(EXP / g / f"states_{s}.csv")
                                           for g in ("on", "off") for s in ("cand", "hold")}
    save_json("manifest.json", manifest)
    print(f"Fresh on byte-equivalent; alignment {manifest['alignment']}", flush=True)


def configs():
    manifest = json.loads((EXP / "manifest.json").read_text())
    assert manifest["base"] == sweep.BASE
    assert manifest["engine_sha256"] == sha(ROOT / "scripts/backtest_valuation_strategy.py")
    width = f"{1 - manifest['alignment']['off_line']:.4f}"
    sides = {g: f"--daily-states {EXP}/{g}/states_cand.csv --hold-states {EXP}/{g}/states_hold.csv"
             for g in ("on", "off")}
    on, off = sides["on"], sides["off"] + f" --width {width}"
    arms = [("BASE", ""), ("REBUILT_CHECK", on)]
    arms += [("OFF" if m == 15 else f"OFF_M{m:02d}", f"{off} --swap-margin {m / 100:.2f}")
             for m in range(10, 21)]
    for cap in range(1, 7):
        arms += [(f"ON_BUY{cap}", f"{on} --max-daily-buys {cap}"),
                 (f"OFF_BUY{cap}", f"{off} --max-daily-buys {cap}")]
    arms += [("OFF_FIXEDLINE", sides["off"]), ("ON_OFFLINE", on + f" --width {width}")]
    assert len(arms) == 27
    return arms


def report(path, name, title):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        sweep.report(path, title)
    (EXP / name).write_text("\n".join(line.rstrip() for line in buffer.getvalue().splitlines()) + "\n", encoding="utf-8")


def main_sweep(workers):
    arms = configs()
    sweep.OUT_DIR = EXP / "summaries"
    sweep.OUT_DIR.mkdir(exist_ok=True)
    common = f" --out-dir {sweep.OUT_DIR}"
    arms = [(label, extra + common) for label, extra in arms]
    (EXP / "configs.txt").write_text("\n".join(f"{l}|{e}" for l, e in arms) + "\n", encoding="utf-8")
    with (EXP / "sweep.txt").open("w", encoding="utf-8") as out:
        run_pass(arms, "", workers, out)
        anchor, winners = sweep.read_top5_winners(sweep.DEFAULT_STARTS)
        assert winners
        out.write(f"#EX5|{anchor}|{winners}\n")
        run_pass(arms, winners, workers, out)
    from dose_table import load
    full, ex, _ = load(EXP / "sweep.txt")
    for group in (full, ex):
        assert group["BASE"] == group["REBUILT_CHECK"], "fresh subset path differs from full production"
    manifest = json.loads((EXP / "manifest.json").read_text())
    manifest.update(excluded_A=winners.split(","), backtest_equivalence="28/28, all summary fields identical")
    save_json("manifest.json", manifest)
    report(EXP / "sweep.txt", "report.txt", "当前 BASE：谷底守卫关闭 × 边际 × 每日笔数")
    artifacts = EXP / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def diagnostic(arm):
        label, extra = arm
        cmd = ([sys.executable, "scripts/backtest_valuation_strategy.py"] + shlex.split(sweep.BASE)
               + shlex.split(extra) + ["--since", "2011-11-01", "--artifacts", "--out-dir", str(artifacts),
                  "--label-suffix", f"_trough_{label}", "--trade-log", str(EXP / f"trades_{label}.csv"),
                  "--candidate-log", str(EXP / f"cands_{label}.csv")])
        run_log(cmd, EXP / f"diag_{label}.txt")
        with (EXP / f"trades_{label}.csv").open(encoding="utf-8-sig") as fh:
            days = collections.Counter(r["date"] for r in csv.DictReader(fh) if r["action"] == "买入")
        if "BUY" in label:
            assert max(days.values(), default=0) <= int(label[-1]), label
        return label, dict(buys=sum(days.values()), buying_days=len(days), max_buys=max(days.values(), default=0))
    selected = [(l, e) for l, e in arms if l in ("BASE", "OFF") or l.startswith("OFF_BUY")]
    with ThreadPoolExecutor(max_workers=min(8, workers)) as pool:
        save_json("buy_count_audit.json", dict(pool.map(diagnostic, selected)))
    print("Completed 756 paths + 8 diagnostics; 28/28 full/subset checks passed", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("prepare", "sweep"))
    ap.add_argument("--workers", type=int, default=60)
    args = ap.parse_args()
    if args.stage == "prepare":
        prepare()
    else:
        main_sweep(args.workers)


if __name__ == "__main__":
    main()

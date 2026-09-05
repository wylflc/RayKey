#!/usr/bin/env python3
"""① 增速腿剂量臂的逐日状态建链与线对齐（§12.155）。

每个 `--roic-trail-weight W` 建两侧、合成持仓侧、按 `align_buy_line.py` 重解买入线，
最后把解填进 `configs/trail_arms.template.txt` 的占位符，写出可直接喂 `sweep_backtest_configs.py`
的配置。**链路先验**：`W=1.0`（即 BASE 口径）那一臂的两侧文件须与生产文件的 v6b 子集逐位相同，
不同即停——否则后面每个 Δ 都是拿两条不同的链在比。

用法（作业里跑，见 scripts/slurm/oi115_trailleg.sbatch）：
    python3 scripts/experimental/build_trailleg_arm_states.py --weights 0.00,0.25,0.50,0.75,1.25
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "data/experiments/exp_oi115_trailleg"
STATES = ROOT / "data/experiments/states/exp_oi115_trailleg"
CODES = ROOT / "data/experiments/exp_oi115_procyclic/configs/v6b_codes.txt"
PANEL = ROOT / "data/processed/pit_attention/panel_moat_bank_v6b.csv"
PROD_CAND = ROOT / "data/processed/a_share_daily_states_adopted.csv"
PROD_HOLD = ROOT / "data/processed/a_share_daily_states_hold.csv"
BASE_LINE, BASE_MARGIN = 0.9343, 0.19

# §6.7 第 2 步的建带命令，逐字对应；两侧只差 B2 的两个开关。
BUILD = ("--value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 "
         "--since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid "
         "--roic-cycle-guard peak --roic-cond-detect graded --roic-peak-ramp 0.3 "
         "--ttm-current on --growth-damp on --thin-equity-max 0.5")
B2_EXTRA = "--ttm-trust on --ttm-trust-delta 0.02"


def tag(w: float) -> str:
    return f"TW{round(w * 100):03d}"


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"失败：{' '.join(cmd)}\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")


def build_side(w: float, side: str) -> None:
    name = f"{tag(w)}_{side}"
    extra = BUILD.split() + (B2_EXTRA.split() if side == "b2" else [])
    run([sys.executable, str(ROOT / "scripts/build_historical_valuation_bands.py"),
         "--codes-file", str(CODES), *extra,
         "--roic-trail-weight", f"{w}",
         "--out-bands", str(STATES / f"bands_{name}.csv"),
         "--out-daily", str(STATES / f"raw_{name}.csv")])
    run([sys.executable, str(ROOT / "scripts/rebuild_bank_bands.py"), "divspread:0.02",
         str(STATES / f"states_{name}.csv"), str(STATES / f"raw_{name}.csv"),
         str(STATES / f"bands_{name}.csv")])


def merge_hold(w: float) -> None:
    run([sys.executable, str(ROOT / "scripts/build_hold_daily_states.py"),
         "--base", str(STATES / f"states_{tag(w)}_cand.csv"),
         "--b2", str(STATES / f"states_{tag(w)}_b2.csv"),
         "--out", str(STATES / f"states_{tag(w)}_hold.csv")])


def digest(path: Path, codes: set[str] | None) -> tuple[str, int]:
    """整份（codes=None）或只取给定代码行的 sha256 与行数；表头计入。"""
    h, n = hashlib.sha256(), 0
    with path.open(newline="", encoding="utf-8") as fh:
        rdr = csv.reader(fh)
        hdr = next(rdr)
        h.update((",".join(hdr) + "\n").encode())
        i = hdr.index("security_code")
        for row in rdr:
            if codes is None or row[i].zfill(6) in codes:
                h.update((",".join(row) + "\n").encode())
                n += 1
    return h.hexdigest(), n


def ratios(path: Path, spans: dict) -> list[float]:
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        rdr = csv.reader(fh)
        hdr = next(rdr)
        ic, idt, iv = (hdr.index(c) for c in ("security_code", "date", "valuation_ratio"))
        for row in rdr:
            code, day = row[ic].zfill(6), row[idt]
            if not any(a <= day <= b for a, b in spans.get(code, ())) or not row[iv]:
                continue
            try:
                out.append(float(row[iv]))
            except ValueError:
                pass
    out.sort()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="0.00,0.25,0.50,0.75,1.25")
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--skip-prior", action="store_true", help="跳过 W=1.0 的链路先验（只在先验已单独跑过时用）")
    args = ap.parse_args()
    weights = [float(x) for x in args.weights.split(",") if x.strip()]
    STATES.mkdir(parents=True, exist_ok=True)

    prior = [] if args.skip_prior else [1.0]
    print(f"[1/4] 建带 + 银行覆盖：{len(weights) + len(prior)} 臂 × 两侧", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda t: build_side(*t),
                      [(w, s) for w in prior + weights for s in ("cand", "b2")]))

    print(f"[2/4] 合成持仓侧", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(merge_hold, prior + weights))

    if prior:
        codes = {ln.strip() for ln in CODES.read_text().split() if ln.strip()}
        for arm_file, prod in ((STATES / "states_TW100_cand.csv", PROD_CAND),
                               (STATES / "states_TW100_hold.csv", PROD_HOLD)):
            a, b = digest(arm_file, None), digest(prod, codes)
            print(f"  链路先验 {arm_file.name} vs 生产 v6b 子集：{a[1]:,} 行｜"
                  f"{'逐位相同' if a == b else '**不同**'}", flush=True)
            if a != b:
                sys.exit("链路先验失败：范围建带与生产文件不一致，停止（否则每个 Δ 都不可信）")

    print("[3/4] 线对齐（对 BASE 同一下侧合格面）", flush=True)
    spans: dict[str, list[tuple[str, str]]] = {}
    with PANEL.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            spans.setdefault(r["security_code"].zfill(6), []).append(
                (r["effective_from"], r.get("effective_to") or "9999-12-31"))
    base = ratios(PROD_CAND, spans)
    share = bisect.bisect_right(base, BASE_LINE) / len(base)
    print(f"  BASE {PROD_CAND.name}：在册观测 {len(base):,}｜买入线 {BASE_LINE:.4f} → 下侧合格面 {share * 100:.3f}%")
    subs = {}
    for w in weights:
        arm = ratios(STATES / f"states_{tag(w)}_cand.csv", spans)
        line = arm[min(int(share * len(arm)), len(arm) - 1)]
        got = bisect.bisect_right(arm, line) / len(arm)
        margin = BASE_MARGIN * line / BASE_LINE
        print(f"  {tag(w)}（W={w}）：在册观测 {len(arm):,}｜买入线 {line:.4f}"
              f"（--width {1 - line:.4f}）→ 合格面 {got * 100:.3f}%｜同倍缩放边际 {margin:.4f}")
        subs[f"@CAND_{tag(w)}@"] = str((STATES / f"states_{tag(w)}_cand.csv").relative_to(ROOT))
        subs[f"@HOLD_{tag(w)}@"] = str((STATES / f"states_{tag(w)}_hold.csv").relative_to(ROOT))
        subs[f"@W_{tag(w)}@"] = f"{1 - line:.4f}"
        subs[f"@M_{tag(w)}@"] = f"{margin:.4f}"

    print("[4/4] 写配置", flush=True)
    text = (EXP / "configs/trail_arms.template.txt").read_text()
    for key, val in subs.items():
        text = text.replace(key, val)
    if "@" in "".join(ln for ln in text.splitlines() if not ln.startswith("#")):
        sys.exit("模板仍有未填占位符，停止")
    out = EXP / "configs/trail_arms.txt"
    out.write_text(text)
    print(f"  已写 {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

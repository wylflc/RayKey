"""OI-205 生产影响：池内 181 只按生产参数与「峰谷守卫全关」（`--roic-peak-k 100`）各跑一次引擎，
取与生产带同一报告期的机械 V 之比，作用到生产机械 V（五粮液取 `pre_research_iv`），P/V 取 09-23 扫描收盘。
OI-205 方案 = 标签 H／F 保留守卫、其余关闭。只作归因，不构成新估值。
    python3 impact.py
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
FLAGS = ("--value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2025-06-30 "
         "--roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak --roic-cond-detect graded "
         "--roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 --roic-trail-weight 0 "
         "--minority-basis earnings --wc-aggregation operating --cash-caliber nonop --equity-anchor guarded "
         "--fade-shape exponential --fade-lambda 0.12 --fade-horizon 50 --roic-ic-floor 0.1").split()   # §6.7 第 2 步
CYCLICAL = {"H", "F"}


def run(codes_file: Path, tmp: Path, tag: str, extra: list[str]) -> dict[tuple[str, str], dict]:
    out = tmp / f"bands_{tag}.csv"
    env = dict(os.environ, RK_STMT_GAP_LOG=str(tmp / f"gaps_{tag}.csv"))
    subprocess.run([sys.executable, str(ROOT / "scripts/build_historical_valuation_bands.py"), "--codes-file", str(codes_file),
                    *FLAGS, *extra, "--out-bands", str(out)], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    return {(r["security_code"], r["report_date"]): r for r in csv.DictReader(out.open(encoding="utf-8-sig"))}


def main() -> None:
    bands = {r["security_code"]: r for r in csv.DictReader((ROOT / "data/processed/a_share_pool_model_bands_adopted.csv").open(encoding="utf-8-sig"))}
    tags = {r["security_code"]: r["strategy_tag_letter"] for r in csv.DictReader((ROOT / "data/interim/strategy_tag_map.csv").open(encoding="utf-8-sig"))}
    scan = {r["security_code"]: r for r in csv.DictReader((ROOT / "data/processed/daily_buy_candidates.csv").open(encoding="utf-8-sig"))}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "codes.txt").write_text("\n".join(sorted(bands)) + "\n")
        base = run(tmp / "codes.txt", tmp, "base", [])
        off = run(tmp / "codes.txt", tmp, "off", ["--roic-peak-k", "100"])
    rows = []
    for code, b in sorted(bands.items()):
        if b.get("roic_path") not in ("growth", "zero_growth") or b.get("status") not in ("", "ok"):
            continue
        key = (code, b["report_date"])
        if key not in base or key not in off:
            continue
        v0, v1 = float(base[key]["intrinsic_value"] or 0), float(off[key]["intrinsic_value"] or 0)
        if v0 <= 0 or v1 <= 0:
            continue
        prod_v = float(b.get("pre_research_iv") or b["intrinsic_value"])
        close = float(scan.get(code, {}).get("close") or 0)
        tag = tags.get(code, "")
        pw, tw = float(b.get("peak_weight") or 0), float(b.get("trough_weight") or 0)
        v_off = prod_v * v1 / v0
        v_oi205 = prod_v if tag in CYCLICAL else v_off
        rows.append(dict(code=code, name=b["security_name"], tag=tag, peak_weight=pw, trough_weight=tw, close=close,
                         v_prod=round(prod_v, 2), v_all_off=round(v_off, 2), v_oi205=round(v_oi205, 2),
                         pv_prod=round(close / prod_v, 3) if close else None,
                         pv_all_off=round(close / v_off, 3) if close else None,
                         pv_oi205=round(close / v_oi205, 3) if close else None))
    with (EXP / "impact.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    moved = [r for r in rows if abs(r["v_oi205"] / r["v_prod"] - 1) > 0.005]
    line = 0.9524
    cross_in = [r["name"] for r in moved if r["pv_prod"] and r["pv_prod"] > line >= r["pv_oi205"]]
    cross_out = [r["name"] for r in moved if r["pv_prod"] and r["pv_prod"] <= line < r["pv_oi205"]]
    summary = dict(n=len(rows), guarded=sum(1 for r in rows if max(r["peak_weight"], r["trough_weight"]) > 0),
                   moved_oi205=len(moved), up=sum(1 for r in moved if r["v_oi205"] > r["v_prod"]),
                   down=sum(1 for r in moved if r["v_oi205"] < r["v_prod"]), cross_in=cross_in, cross_out=cross_out)
    (EXP / "impact.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False))
    for r in sorted(moved, key=lambda r: r["v_oi205"] / r["v_prod"]):
        print(f"{r['code']} {r['name']:6} {r['tag']} w={r['peak_weight']:.2f} v={r['trough_weight']:.2f} V {r['v_prod']:>8} → {r['v_oi205']:>8}"
              f" ({r['v_oi205'] / r['v_prod'] - 1:+.0%})  P/V {r['pv_prod']} → {r['pv_oi205']}")


if __name__ == "__main__":
    main()

"""§7.3 结构性增长复核（OI-249、OI-250）：峰守卫是否把结构性的回报上台阶当成周期高点。

生产候选侧池带中 ROIC 路径、峰守卫权重 w > 0 的公司，用建带脚本按 §6.7 第 2 步参数当晚重建三次（同一数据版本）：
- 原样：取峰守卫下的每股 NOPAT；
- 研究开关 `--peak-relax volume`：w 置 0 即判量驱动（最新年报营收较两年前年报年复合 ≥ 25%、毛利率两年升幅 ≤ 5pp、
  两年窗口内无外生权益变动、购买法收购与主体重置）；
- `--roic-peak-k 99`：不设峰守卫的每股 NOPAT。
`1 − 原样每股 NOPAT ÷ 不设峰守卫值 ≥ 40%`，且量驱动或业务属性登记为结构成长型（个人投资体系第 5.12 节，
`a_share_business_attributes.csv`）的记 `flagged`，由 `build_report_update_queue.py` 入队复核（不冻结）。
`commodity` 列标出东财 2016 行业属商品定价型（建带脚本 `OI249_COMMODITY_PREFIXES`）的公司，供复核参考，不影响入队。

    python3 scripts/structural_growth_review.py --signal-date YYYY-MM-DD    # → data/interim/structural_growth_review.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
DEFAULT_BANDS = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
DEFAULT_OUTPUT = ROOT / "data/interim/structural_growth_review.csv"
DEFAULT_BUSINESS = ROOT / "data/processed/a_share_business_attributes.csv"
GROWTH_CLASS = "结构成长型"
ROIC_PATHS = {"growth", "zero_growth"}
CUT_MIN = 0.40
# §6.7 第 2 步建带参数（改 §6.7 时同步此处）
BUILD_FLAGS = ("--value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 "
               "--roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak --roic-cond-detect graded "
               "--roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 --roic-trail-weight 0 "
               "--minority-basis earnings --wc-aggregation operating --cash-caliber nonop --equity-anchor guarded "
               "--restricted-cash notes_wc --wacc-weights unlevered --reset-guard both --rd-capitalize on "
               "--fade-shape exponential --fade-lambda 0.12 --fade-horizon 50 --roic-ic-floor 0.1").split()
FIELDS = ["security_code", "security_name", "report_date", "available_at", "peak_weight", "nopat_ps_guarded", "nopat_ps_unguarded",
          "cut", "volume_driven", "business_class", "trigger", "flagged", "commodity", "em2016", "v_guarded", "v_unguarded",
          "band_match", "signal_date"]
INDUSTRY = ROOT / "data/reference/a_share_csrc_industry.csv"


def industries() -> dict[str, tuple[str, bool]]:
    from build_historical_valuation_bands import OI249_COMMODITY_PREFIXES
    out = {}
    if INDUSTRY.exists():
        with INDUSTRY.open(newline="", encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                em = (r.get("em2016") or "").strip()
                out[r["security_code"]] = (em, any(em == p or em.startswith(p + "-") for p in OI249_COMMODITY_PREFIXES))
    return out


def business_classes(path: Path) -> dict[str, str]:
    """个人投资体系第 5.12 节的登记表：代码 → 派生类别（未登记的不在表内）。"""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"].zfill(6): (r.get("derived_class") or "").strip() for r in csv.DictReader(handle)}


def _num(value) -> float | None:
    try:
        return float(value) if value not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def guarded_rows(bands_path: Path) -> list[dict[str, str]]:
    with bands_path.open(newline="", encoding="utf-8") as handle:
        return [r for r in csv.DictReader(handle)
                if r.get("roic_path") in ROIC_PATHS and (_num(r.get("peak_weight")) or 0.0) > 0]


def build(codes: list[str], extra: list[str], workdir: Path, tag: str) -> dict[tuple[str, str, str], dict[str, str]]:
    out_bands, out_daily = workdir / f"bands_{tag}.csv", workdir / f"daily_{tag}.csv"
    env = dict(os.environ, RK_STMT_GAP_LOG=str(workdir / f"gaps_{tag}.csv"))
    subprocess.run([sys.executable, str(ROOT / "scripts/build_historical_valuation_bands.py"), "--codes", ",".join(codes),
                    *BUILD_FLAGS, *extra, "--out-bands", str(out_bands), "--out-daily", str(out_daily)],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    with out_bands.open(newline="", encoding="utf-8") as handle:
        return {(r["security_code"], r["report_date"], r["available_at"]): r for r in csv.DictReader(handle)}


def latest_key(bands: dict, code: str, signal_date: str) -> tuple[str, str, str] | None:
    keys = [k for k, r in bands.items() if k[0] == code and r.get("status") == "ok" and k[2] <= signal_date]
    return max(keys, key=lambda k: (k[2], k[1])) if keys else None


def review(pool_rows: list[dict[str, str]], guarded: dict, relaxed: dict, unguarded: dict, signal_date: str,
           cut_min: float = CUT_MIN, industry: dict | None = None, business: dict | None = None) -> list[dict]:
    rows = []
    industry, business = industry or {}, business or {}
    for pool in sorted(pool_rows, key=lambda r: r["security_code"]):
        code = pool["security_code"].zfill(6)
        key = (code, pool.get("report_date", ""), pool.get("available_at", ""))
        match = "pool_band"
        if key not in guarded:
            key, match = latest_key(guarded, code, signal_date), "latest_rebuilt"
        g, r, u = ((guarded.get(key), relaxed.get(key), unguarded.get(key)) if key else (None, None, None))
        business_class = business.get(code, "")
        if not g or not r or not u:
            rows.append(dict(security_code=code, security_name=pool.get("security_name", ""), band_match="missing",
                             business_class=business_class, signal_date=signal_date, volume_driven=False, flagged=False))
            continue
        w_g, w_r = _num(g.get("peak_weight")) or 0.0, _num(r.get("peak_weight")) or 0.0
        n_g, n_u = _num(g.get("nopat_ps")), _num(u.get("nopat_ps"))
        volume = w_g > 0 and w_r == 0.0
        cut = 1.0 - n_g / n_u if w_g > 0 and n_g is not None and n_u and n_u > 0 else None
        trigger = "+".join(t for t, hit in (("volume", volume), ("business", business_class == GROWTH_CLASS)) if hit)
        rows.append(dict(security_code=code, security_name=pool.get("security_name", ""), report_date=key[1], available_at=key[2],
                         peak_weight=f"{w_g:.3f}", nopat_ps_guarded=f"{n_g:.4f}" if n_g is not None else "",
                         nopat_ps_unguarded=f"{n_u:.4f}" if n_u is not None else "", cut=f"{cut:.4f}" if cut is not None else "",
                         volume_driven=volume, business_class=business_class, trigger=trigger,
                         flagged=bool(trigger and cut is not None and cut >= cut_min),
                         v_guarded=g.get("intrinsic_value", ""), v_unguarded=u.get("intrinsic_value", ""),
                         commodity=industry.get(code, ("", False))[1], em2016=industry.get(code, ("", False))[0],
                         band_match=match, signal_date=signal_date))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--bands", type=Path, default=DEFAULT_BANDS, help="生产候选侧池带（ROIC 路径与峰守卫权重取自此）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cut-min", type=float, default=CUT_MIN)
    parser.add_argument("--business", type=Path, default=DEFAULT_BUSINESS, help="业务属性登记（个人投资体系第 5.12 节）")
    args = parser.parse_args()
    pool_rows = guarded_rows(args.bands)
    codes = sorted({r["security_code"].zfill(6) for r in pool_rows})
    rows = []
    if codes:
        with tempfile.TemporaryDirectory(prefix="sgr_", dir=str(ROOT / "data/interim")) as tmp:
            workdir = Path(tmp)
            guarded = build(codes, [], workdir, "guarded")
            relaxed = build(codes, ["--peak-relax", "volume"], workdir, "relaxed")
            unguarded = build(codes, ["--roic-peak-k", "99"], workdir, "unguarded")
        rows = review(pool_rows, guarded, relaxed, unguarded, args.signal_date, args.cut_min, industries(),
                      business_classes(args.business))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    from daily_execution_guard import stamp
    stamp(args.output, args.signal_date, (args.bands,) + ((args.business,) if args.business.exists() else ()))
    flagged = [f"{r['security_name']}（{float(r['cut']):.0%}，{r['trigger']}{'，商品定价型' if r.get('commodity') else ''}）"
               for r in rows if r.get("flagged")]
    volume = sum(1 for r in rows if r.get("volume_driven"))
    unregistered = sum(1 for r in rows if not r.get("business_class"))
    print(f"structural growth review: {len(rows)} guarded pool bands, {volume} volume-driven, {unregistered} without business attributes, "
          f"{len(flagged)} flagged"
          + (f"：{'、'.join(flagged)}" if flagged else ""))


if __name__ == "__main__":
    main()

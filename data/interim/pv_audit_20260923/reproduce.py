#!/usr/bin/env python3
"""P/V 估值逻辑审计（2026-09-23）的复现脚本。

只读生产产物，引擎重跑与中间文件一律写临时目录（`RK_STMT_GAP_LOG` 同时改道），不改任何生产文件。
输出 `observations.csv`：池内每只股票的生产读数与四个单变量反事实，用于归因，不是新估值。

    python3 data/interim/pv_audit_20260923/reproduce.py            # 约 1 分钟、<200 MB
    python3 data/interim/pv_audit_20260923/reproduce.py --out /tmp/x.csv

反事实（每次只改一处，其余与生产相同）：
  PV_newcap   回报衰减只作用于新增资本（`intrinsic_value(consistent=False)`，由带文件的输入直接复算）
  PV_w1       增速腿权重 `--roic-trail-weight 1`（引擎重跑）
  PV_noguard  峰／谷守卫关闭（`--roic-peak-k 100`，引擎重跑）
  PV_cash     超额现金补入拆出资金、买入返售、债权投资、其他债权投资并扣吸收存款（只加确定项，不含其他流动资产等）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from intrinsic_value import ValuationError, intrinsic_value  # noqa: E402

BANDS = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
QUOTES = ROOT / "data/processed/daily_buy_candidates.csv"
STMT = ROOT / "data/raw/financials_statements"
ENGINE_FLAGS = ("--value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2026-06-30 "
                "--roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak --roic-cond-detect graded "
                "--roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 "
                "--minority-basis earnings --wc-aggregation operating").split()
CASH_CERTAIN = ("LEND_FUND", "BUY_RESALE_FINASSET", "CREDITOR_INVEST", "OTHER_CREDITOR_INVEST")
CASH_DEPOSIT_LIKE = ("OTHER_CURRENT_ASSET", "NONCURRENT_ASSET_1YEAR", "OTHER_NONCURRENT_ASSET")
DEPOSITS_TAKEN = ("ACCEPT_DEPOSIT_INTERBANK", "ACCEPT_DEPOSIT")


def run_engine(codes_file: Path, tmp: Path, tag: str, extra: list[str]) -> pd.DataFrame:
    out = tmp / f"bands_{tag}.csv"
    env = dict(os.environ, RK_STMT_GAP_LOG=str(tmp / f"gaps_{tag}.csv"))
    cmd = [sys.executable, str(ROOT / "scripts/build_historical_valuation_bands.py"), "--codes-file", str(codes_file),
           *ENGINE_FLAGS, *extra, "--out-bands", str(out)]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    df = pd.read_csv(out, dtype={"security_code": str})
    return df[df.report_date == "2026-06-30"].set_index("security_code")


def statement_rows(kind: str, cols: list[str], codes: set[str]) -> pd.DataFrame:
    parts = []
    for chunk in pd.read_csv(STMT / f"{kind}.csv", usecols=lambda c: c in cols, dtype={"security_code": str},
                             chunksize=20000):
        chunk["security_code"] = chunk.security_code.str.zfill(6)
        parts.append(chunk[chunk.security_code.isin(codes) & (chunk.REPORT_DATE.str[:10] == "2025-12-31")])
    df = pd.concat(parts).drop_duplicates("security_code", keep="last").set_index("security_code")
    for c in cols:
        if c not in ("security_code", "REPORT_DATE"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def newcap_value(row: pd.Series) -> float | None:
    """生产带输入不变，只把留存式换成「衰减作用于新增资本」；V 按 EV 变化经少数股东份额传到归母。"""
    if row.roic_path != "growth" or pd.isna(row.ev_ps):
        return None
    rt = min(row.wacc + 0.02, row.roic0)
    try:
        base = intrinsic_value(row.nopat_ps, row.roic0, row.g0, row.wacc, roe_terminal=rt, g_terminal=0.03, n=10)
        alt = intrinsic_value(row.nopat_ps, row.roic0, row.g0, row.wacc, roe_terminal=rt, g_terminal=0.03, n=10,
                              consistent=False)
    except ValuationError:
        return None
    m = row.minority_share if pd.notna(row.minority_share) else 0.0
    book = max(row.minority_book_ps, 0.0) if pd.notna(row.minority_book_ps) else 0.0
    keep = (1 - m) if m * max(base.intrinsic_value - row.fin_net_debt_ps, 0) >= book else 1.0
    scale = row.intrinsic_value / (base.intrinsic_value - row.net_debt_ps)   # 除权归一化与预告叠加的比例
    return row.intrinsic_value + (alt.intrinsic_value - base.intrinsic_value) * keep * scale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("observations.csv"))
    args = parser.parse_args()

    bands = pd.read_csv(BANDS, dtype={"security_code": str}).set_index("security_code")
    quotes = pd.read_csv(QUOTES, dtype={"security_code": str}).set_index("security_code")
    codes = set(bands.index)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        codes_file = tmp / "codes.txt"
        codes_file.write_text("\n".join(sorted(codes)) + "\n", encoding="utf-8")
        w0 = run_engine(codes_file, tmp, "w0", ["--roic-trail-weight", "0"])
        w1 = run_engine(codes_file, tmp, "w1", ["--roic-trail-weight", "1"])
        k100 = run_engine(codes_file, tmp, "k100", ["--roic-trail-weight", "0", "--roic-peak-k", "100"])

    bal = statement_rows("balance", ["security_code", "REPORT_DATE", *CASH_CERTAIN, *CASH_DEPOSIT_LIKE,
                                     *DEPOSITS_TAKEN, "AGENT_TRADE_SECURITY", "TOTAL_PARENT_EQUITY"], codes)
    inc = statement_rows("income", ["security_code", "REPORT_DATE", "TOTAL_PROFIT", "FE_INTEREST_EXPENSE",
                                    "FE_INTEREST_INCOME"], codes)

    rows = []
    for code, b in bands.iterrows():
        close = quotes.close.get(code)
        v = quotes.model_intrinsic_value.get(code)   # 扫描器读数：银行／保险的利率按信号日重读，与带文件略有差异
        rec = dict(security_code=code, security_name=b.security_name, roic_path=b.roic_path,
                   trade_date=quotes.trade_date.get(code), close=close, V=v, PV=quotes.model_pv.get(code),
                   pe_ttm=close / b.eps_ttm if pd.notna(b.eps_ttm) and b.eps_ttm else None,
                   nopat_over_eps=b.nopat_ps / b.eps_ttm if pd.notna(b.eps_ttm) and b.eps_ttm else None,
                   ev_over_nopat=b.ev_ps / b.nopat_ps if pd.notna(b.ev_ps) and b.nopat_ps else None,
                   roic0=b.roic0, wacc=b.wacc, g0=b.g0, peak_weight=b.peak_weight, trough_weight=b.trough_weight,
                   growth_trust=b.growth_trust, cash_counted_ps=-b.fin_net_debt_ps if pd.notna(b.fin_net_debt_ps) else None)
        # 引擎重跑的是未除权、未叠加的原始带：按「反事实 ÷ 同批 W=0 原始值」的比例作用到生产 V
        if b.roic_path in ("growth", "zero_growth") and pd.notna(v) and v > 0 and code in w0.index:
            base_raw = w0.intrinsic_value[code]
            if base_raw > 0:
                if code in w1.index:
                    rec["PV_w1"] = close / (v * w1.intrinsic_value[code] / base_raw)
                    rec["g0_w1"] = w1.g0[code]
                if code in k100.index:
                    rec["PV_noguard"] = close / (v * k100.intrinsic_value[code] / base_raw)
        nv = newcap_value(b)
        rec["PV_newcap"] = close / nv if nv else None
        if code in bal.index and b.roic_path in ("growth", "zero_growth") and pd.notna(b.bps) and b.bps > 0:
            r = bal.loc[code]
            shares = r.TOTAL_PARENT_EQUITY / b.bps
            certain = sum(r[c] for c in CASH_CERTAIN) - sum(r[c] for c in DEPOSITS_TAKEN)
            rec["cash_certain_missed_ps"] = certain / shares
            rec["deposit_like_lines_ps"] = sum(r[c] for c in CASH_DEPOSIT_LIKE) / shares
            rec["client_funds_ps"] = r.AGENT_TRADE_SECURITY / shares
            if pd.notna(v) and v > 0 and r.AGENT_TRADE_SECURITY <= 0:   # 券商型资产负债表不适用
                rec["PV_cash"] = close / (v + max(certain, 0.0) / shares)
        if code in inc.index:
            i = inc.loc[code]
            ebit = i.TOTAL_PROFIT + i.FE_INTEREST_EXPENSE
            rec["interest_income_pct_ebit"] = i.FE_INTEREST_INCOME / ebit if ebit > 0 else None
        rows.append(rec)
    out = pd.DataFrame(rows).sort_values("PV")
    out.to_csv(args.out, index=False, float_format="%.4f")
    print(f"{len(out)} 行 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

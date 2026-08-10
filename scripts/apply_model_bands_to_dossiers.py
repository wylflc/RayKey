#!/usr/bin/env python3
"""把内在价值模型的带写入逐票档案（§6.5.7.3，v2.72 起为唯一带来源）。

为什么要有这一步
----------------
2026-08-10 查出**回测用的带与实盘出单的带不是同一套**（§12.9.1）：回测读
`intrinsic_value.py` 的机械模型（`g0 = ROE×留存率`、10 年 fade、隐含 PE 中位 15.0），
而实盘出单用 273 份手工档案（169 份走 `一致预期 × PEG`，隐含 PE 20~45x）。
两者中位相差 **1.24 倍**——即实盘等效运行在买入线约 1.12 上，超出 §12.6 扫过的
0.70~1.00 全区间，且落在「越松越差」的一侧。

用户 2026-08-10 裁定：**按回测口径落实，因为那是经过验证的模型。**

口径对齐（关键）
----------------
模型输出 `band = IV × [0.90, 1.10]`，**中值恰为 `IV`**；回测的
`valuation_ratio = 收盘 / IV`。故把该带写入档案后，生产口径的
`P/V = 收盘 ÷ 区间中值` 与回测**逐位一致**，不引入任何换算误差。

保留逐票档案的哪一部分
----------------------
**只覆盖带相关的六列**（`band_low`/`band_high`/`band_method`/`band_derivation`/
`anchor_earnings_yi`/`reviewed_at`）。`key_metrics`、`hf_indicators`、
`next_earnings_check`、`review_triggers`、`dossier_dir`、`notes` 原样保留——
那是逐票研究的结论，与用哪个模型算带无关，且 §7.4.1 的复核触发仍要用它。
原带写入 `notes` 留痕，可追溯。

什么情况下仍用手工带（`bespoke` 保持 true）
------------------------------------------
1. **模型判不可估**：`EPS0 ≤ 0` 或 `ROE0 ≤ 0`（亏损或归一化 ROE 为负）。
   §6.5.5.2 明文要求此时转逐票推导，不得判「无法估值」。判例：寒武纪
   2021-24 连亏四年，五年归一化 ROE 为负。
2. **模型带时点过旧**（`--min-available` 之前）：主体重组后旧财报不可比。
   判例：宏桥控股 2024 年资产注入，模型最新带停在 2012-10。

用法
----
    python3 scripts/build_historical_valuation_bands.py --codes-file <池代码> \
        --since 2000-01-01 --r-mode market \
        --out-bands data/interim/pool_model_bands.csv --out-daily /tmp/x.csv
    python3 scripts/apply_model_bands_to_dossiers.py --bands data/interim/pool_model_bands.csv --as-of YYYY-MM-DD

随后照常跑 §6.7 四步链（建带卡 → apply → 校验 → 池物化）。
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"


def latest_model_bands(path: Path, min_available: str) -> tuple[dict, dict]:
    """每只取 `available_at` 最新且可用的一条。返回 (可用带, 被时点门槛挡下的)。"""
    best: dict[str, dict] = {}
    for row in csv.DictReader(path.open(newline="", encoding="utf-8-sig")):
        if row.get("status") != "ok":
            continue
        try:
            if float(row["intrinsic_value"]) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        code, avail = row["security_code"], row.get("available_at", "")
        if code not in best or avail > best[code]["available_at"]:
            best[code] = row
    stale = {c: r for c, r in best.items() if r["available_at"][:10] < min_available}
    return {c: r for c, r in best.items() if c not in stale}, stale


def main() -> int:
    ap = argparse.ArgumentParser(description="把内在价值模型的带写入逐票档案")
    ap.add_argument("--bands", type=Path, default=ROOT / "data/interim/pool_model_bands.csv")
    ap.add_argument("--dossiers", type=Path, default=DOSSIERS)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--min-available", default="2025-01-01",
                    help="模型带的 available_at 早于此即视为时点过旧，保留手工带")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    usable, stale = latest_model_bands(args.bands, args.min_available)
    rows = list(csv.DictReader(args.dossiers.open(newline="", encoding="utf-8-sig")))
    header = list(rows[0].keys())

    applied, kept_unvaluable, kept_stale = [], [], []
    for row in rows:
        code = row["security_code"]
        band = usable.get(code)
        if band is None:
            (kept_stale if code in stale else kept_unvaluable).append(row["security_name"])
            continue

        iv = float(band["intrinsic_value"])
        old_low, old_high = row["band_low"], row["band_high"]
        old_mid = (float(old_low) + float(old_high)) / 2 if old_low and old_high else None

        row["band_low"] = f"{iv * 0.90:.2f}"
        row["band_high"] = f"{iv * 1.10:.2f}"
        # **`bespoke` 必须保持 `true`**：它的语义是「带只由本档给出，通用十类模型不参与」，
        # 而本档现在装的正是模型带。设成 `false` 会让 `build_valuation_band_cards.py` 走通用路径
        # 把带覆盖掉——2026-08-10 首次落地时正是这么错的，17 只被重算成兜底 EPV 后判无法估值。
        row["bespoke"] = "true"
        row["band_method"] = "内在价值模型（§6.5.7.3）：ROE—再投资—增长—可分配现金—折现"
        row["band_derivation"] = (
            f"`intrinsic_value.py` 主模型，与 §12.9 回测所用带**同一套口径**。"
            f"报告期 {band['report_date'][:10]}、生效日 {band['available_at'][:10]}｜"
            f"eps0 {band['eps0']}、roe0 {float(band['roe0']):.2%}"
            f"（{band.get('roe_source', '')}，近五年归一化）｜"
            f"g0 {float(band['g0']):.2%} = ROE × (1 − 派息率 {float(band['payout'] or 0):.0%})"
            f"{'（**已触 g0 上限 25%**）' if band.get('g0_capped') == 'Y' else ''}｜"
            f"r {float(band['r']):.2%}（Rf+β·ERP，取报告期当时利率）｜"
            f"g_T {float(band['g_terminal']):.2%}、ROE_T {float(band['roe_terminal']):.2%}｜"
            f"10 年线性 fade（n1=0，自第 1 年起衰减）｜"
            f"**内在价值 {iv:.2f} 元**，隐含 PE {band['implied_pe'][:6]}、"
            f"终值占比 {float(band['terminal_share']):.0%}。"
            f"带 = IV × [0.90, 1.10]，**中值恰为 IV**，故 `P/V = 收盘 ÷ 中值` 与回测的 "
            f"`valuation_ratio = 收盘 ÷ IV` 逐位一致。"
        )
        row["anchor_earnings_yi"] = ""      # 本模型按每股折现，不用亿元口径的利润锚
        row["reviewed_at"] = args.as_of
        row["decided_by"] = "内在价值模型（v2.72 起唯一带来源）"
        note = (f"**{args.as_of} 换用内在价值模型带（v2.72）**：原手工带 "
                f"{old_low}~{old_high}" + (f"（中值 {old_mid:.2f}，为模型带的 {old_mid / iv:.2f}x）"
                                           if old_mid else "") +
                f" → {row['band_low']}~{row['band_high']}。"
                f"换的理由见 §12.9.1：原档案带与回测所用带中位差 1.24 倍，"
                f"等效把买入线抬到约 1.12，超出 §12.6 验证过的全区间。")
        row["notes"] = note + ("｜" + row["notes"] if row["notes"] else "")
        applied.append(row["security_name"])

    print(f"档案 {len(rows)} 份｜**改用模型带 {len(applied)} 份**")
    if kept_unvaluable:
        print(f"  保留手工带·模型判不可估 {len(kept_unvaluable)} 只：{'、'.join(kept_unvaluable)}")
    if kept_stale:
        print(f"  保留手工带·模型带早于 {args.min_available} {len(kept_stale)} 只："
              f"{'、'.join(kept_stale)}")
    only_model = set(usable) - {r['security_code'] for r in rows}
    if only_model:
        print(f"  ⚠ 有模型带但无档案 {len(only_model)} 只（不写入，档案是唯一载体）")

    if args.dry_run:
        print("  （dry-run，未写盘）")
        return 0
    with args.dossiers.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  写入 {args.dossiers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

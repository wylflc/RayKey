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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_historical_valuation_bands import load_actions, split_factor  # noqa: E402

DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"


def latest_model_bands(path: Path, min_available: str) -> tuple[dict, dict]:
    """每只取最新且可用的一条。返回 (可用带, 被时点门槛挡下的)。

    **排序键必须是 `(available_at, report_date)` 两项**：A 股年报与一季报绝大多数在同一天
    披露（4/29-4/30），两条的 `available_at` 因此相等；只比 `available_at` 时严格 `>` 不成立，
    先读到的那条（文件按报告期升序，即**年报**）会留下来，一季报被丢掉。
    2026-08-10 v2.72 首次落地即踩此坑——168 只可比标的中 **59 只用了上一期报告的带**，
    且方向一致偏低（格力电器 108.54 而非 113.07、五粮液 107.30 而非 114.51），
    与回测面板逐票对不上。回测面板本身取值正确，故这**只是生产侧的选择错**，不是口径分歧。
    """
    best: dict[str, dict] = {}
    for row in csv.DictReader(path.open(newline="", encoding="utf-8-sig")):
        if row.get("status") != "ok":
            continue
        try:
            if float(row["intrinsic_value"]) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        code = row["security_code"]
        key = (row.get("available_at", ""), row.get("report_date", ""))
        if code not in best or key > (best[code]["available_at"], best[code]["report_date"]):
            best[code] = row
    stale = {c: r for c, r in best.items() if r["available_at"][:10] < min_available}
    return {c: r for c, r in best.items() if c not in stale}, stale


def main() -> int:
    ap = argparse.ArgumentParser(description="把内在价值模型的带写入逐票档案")
    # v4.01：缺省改指 §6.7 第①步的采纳产物。旧缺省 data/interim/pool_model_bands.csv 是
    # v2.72 DCF 时代的一次性物化，2026-08-17 曾以缺省身份把 8-10 的陈旧带写回档案（当日发现即修）。
    ap.add_argument("--bands", type=Path,
                    default=ROOT / "data/processed/a_share_pool_model_bands_adopted.csv")
    ap.add_argument("--dossiers", type=Path, default=DOSSIERS)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--min-available", default="2025-01-01",
                    help="模型带的 available_at 早于此即视为时点过旧，保留手工带")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    usable, stale = latest_model_bands(args.bands, args.min_available)
    rows = list(csv.DictReader(args.dossiers.open(newline="", encoding="utf-8-sig")))
    header = list(rows[0].keys())
    actions = load_actions()

    applied, kept_unvaluable, kept_stale, split_adj = [], [], [], []
    for row in rows:
        code = row["security_code"]
        band = usable.get(code)
        if band is None:
            (kept_stale if code in stale else kept_unvaluable).append(row["security_name"])
            continue

        # **送转必须在这里再除一次**：`intrinsic_value` 是报告期口径的每股价值，而现价是不复权的。
        # 该报告公告之后若发生送转，股数变了而 `IV` 没变，带就与价格不同基——带偏高一个送转比，
        # `P/V` 相应偏低。回测面板的 `split_factor` 列做的正是这件事，生产侧此前漏做：
        # 2026-08-10 复核发现 18 只不一致，全部是 1.30/1.40/1.45 三个送转比
        # （兴齐眼药 2026-05-22 十送四点五，带 25.80 应为 17.80，`P/V` 1.66 实为 **2.41**）。
        # `since` 取该期**公告日**而非报告期末，理由同 `split_factor` 的文档串。
        factor = split_factor(actions.get(code, []), band["notice_date"], args.as_of)
        iv = float(band["intrinsic_value"]) / factor
        if factor != 1.0:
            split_adj.append(f"{row['security_name']}÷{factor:g}")
        old_low, old_high = row["band_low"], row["band_high"]
        old_mid = (float(old_low) + float(old_high)) / 2 if old_low and old_high else None

        row["band_low"] = f"{iv * 0.90:.2f}"
        row["band_high"] = f"{iv * 1.10:.2f}"
        # **`bespoke` 必须保持 `true`**：它的语义是「带只由本档给出，通用十类模型不参与」，
        # 而本档现在装的正是模型带。设成 `false` 会让 `build_valuation_band_cards.py` 走通用路径
        # 把带覆盖掉——2026-08-10 首次落地时正是这么错的，17 只被重算成兜底 EPV 后判无法估值。
        row["bespoke"] = "true"
        # v4.00：带来源分四条路径（§6.5.7.3），派生说明按路径写，不再一律套权益 DCF 的口径
        roic_path = (band.get("roic_path") or "").strip()
        common_head = (f"与 §9.7.1.2 回测所用带**同一套口径**。"
                       f"报告期 {band['report_date'][:10]}、生效日 {band['available_at'][:10]}｜")
        common_tail = (f"**内在价值 {iv:.2f} 元**。带 = IV × [0.90, 1.10]，**中值恰为 IV**，"
                       f"故 `P/V = 收盘 ÷ 中值` 与回测的 `valuation_ratio` 逐位一致。")
        def _f(key, fmt="{:.2%}"):
            try:
                return fmt.format(float(band.get(key) or 0))
            except (TypeError, ValueError):
                return "—"
        if roic_path == "bank_divspread":
            row["band_method"] = "银行·股利折现（§6.5.7.3）"
            row["band_derivation"] = (common_head
                + "V = 近 12 个月每股现金分红 ÷ (十年国债 + 2%)｜" + common_tail)
        elif roic_path in ("growth", "zero_growth"):
            row["band_method"] = "内在价值模型·ROIC 口径（§6.5.7.3）：NOPAT—投入资本—增量回报—WACC—EV−净负债"
            row["band_derivation"] = (common_head
                + f"每股 NOPAT {band.get('nopat_ps', '—')}｜ROIC0 {_f('roic0')}｜"
                + f"增量 ROIC {_f('incremental_roic')}｜再投资率 {_f('reinvestment_rate')}｜"
                + f"g0 {_f('g0')} = 增量ROIC × 再投资率｜WACC {_f('wacc')}｜"
                + f"终值 ROIC {_f('roe_terminal')}、g_T {_f('g_terminal')}｜"
                + f"每股净负债 {band.get('net_debt_ps', '—')}｜"
                + ("**零增长永续**（增长输入不可用，V = NOPAT/WACC − 净负债）｜"
                   if roic_path == "zero_growth" else "")
                + common_tail)
        else:
            row["band_method"] = "内在价值模型·权益退路（§6.5.7.3：无三大报表时的权益 DCF）"
            row["band_derivation"] = (common_head
                + f"eps0 {band.get('eps0', '—')}、roe0 {_f('roe0')}（{band.get('roe_source', '')}）｜"
                + f"g0 {_f('g0')} = ROE × 留存率｜r {_f('r')}｜"
                + f"g_T {_f('g_terminal')}、ROE_T {_f('roe_terminal')}｜" + common_tail)
        row["anchor_earnings_yi"] = ""      # 本模型按每股折现，不用亿元口径的利润锚
        row["reviewed_at"] = args.as_of
        row["decided_by"] = "内在价值模型（§6.5.7.3 唯一带来源；v4.00 起 ROIC 口径）"
        note = (f"**{args.as_of} 换用 v4.00 ROIC 口径带**：原带 "
                f"{old_low}~{old_high}" + (f"（中值 {old_mid:.2f}，为新带的 {old_mid / iv:.2f}x）"
                                           if old_mid else "") +
                f" → {row['band_low']}~{row['band_high']}。依据 §12.66~§12.69。")
        row["notes"] = note + ("｜" + row["notes"] if row["notes"] else "")
        applied.append(row["security_name"])

    print(f"档案 {len(rows)} 份｜**改用模型带 {len(applied)} 份**")
    if split_adj:
        print(f"  送转折算 {len(split_adj)} 只：{'、'.join(split_adj)}")
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

#!/usr/bin/env python3
"""把生产模型带写入逐票档案；池外档案从全市场模型带取数。

只更新估值字段；研究指标和备注保留。不可估时清空带，主体不可比按
工作流程登记重置事件后重建。用 --dry-run 预览，--signal-date 指定信号日。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_historical_valuation_bands import load_actions  # noqa: E402
from apply_forecast_band_overlay import exright_normalize  # noqa: E402
from a_share_signal_dates import evidence_iso_for_signal  # noqa: E402
from divspread_names import is_divspread_financial  # noqa: E402  v4.56 银行＋保险股利折现
from screen_daily_volume_price_signals import bank_dividend_intrinsic  # noqa: E402


def csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def latest_rf(as_of: str) -> float | None:
    """十年国债截至信号日的最新观测，无可用观测时返回 None。"""
    path = ROOT / "data/reference/cost_of_equity_inputs.csv"
    if not path.exists():
        return None
    best = None
    for r in csv_rows(path):
        try:
            key = r.get("observed_on") or ""
            if key and key <= as_of and (best is None or key > best[0]):
                best = (key, float(r["risk_free_rate"]))
        except (TypeError, ValueError):
            continue
    return best[1] if best else None

DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"


def latest_model_bands(path: Path, min_available: str, codes: set[str] | None = None,
                       as_of: str | None = None) -> tuple[dict, dict]:
    """按 (available_at, report_date) 取最新可用带，返回可用与过旧两组。"""
    best: dict[str, dict] = {}
    import roic_inputs
    reset = roic_inputs.load_entity_reset()
    post_seen: set[str] = set()
    if reset:
        for row in csv_rows(path):
            c = row.get("security_code") or ""
            if c in reset and (row.get("report_date") or "") >= reset[c]["reset"] \
                    and (not as_of or (row.get("available_at") or "")[:10] <= as_of):
                post_seen.add(c)
    for row in csv_rows(path):
        if codes is not None and row.get("security_code") not in codes:
            continue                                  # v4.54：全市场带文件只看池外档案代码
        if as_of and (row.get("available_at") or "")[:10] > as_of:
            continue
        if row.get("status") != "ok":
            continue
        if roic_inputs.reset_supersedes(reset, row.get("security_code") or "", row.get("report_date") or "",
                                        (row.get("security_code") or "") in post_seen):
            continue                                  # §6.5.2.4 主体重置：重置前的带不再沿用
        try:
            if float(row["intrinsic_value"]) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        code = row["security_code"]
        key = (row.get("available_at", ""), row.get("report_date", ""))
        if code not in best or key > (best[code]["available_at"], best[code]["report_date"]):
            best[code] = row
    if any(r.get("forecast_overlay") == "manual_override" for r in best.values()):
        raise ValueError("模型带含人工覆盖值，请按工作流程重建模型带")
    stale = {c: r for c, r in best.items() if r["available_at"][:10] < min_available}
    return {c: r for c, r in best.items() if c not in stale}, stale


def main() -> int:
    ap = argparse.ArgumentParser(description="把内在价值模型的带写入逐票档案")
    ap.add_argument("--bands", type=Path,
                    default=ROOT / "data/processed/a_share_pool_model_bands_adopted.csv")
    ap.add_argument("--archive-bands", type=Path, default=ROOT / "data/processed/roic_bands.csv",
                    help="池外档案的模型带来源；只落档案，仅在文件存在时读取")
    ap.add_argument("--dossiers", type=Path, default=DOSSIERS)
    ap.add_argument("--signal-date", required=True, help="信号日；证据日自动取下一工作日")
    ap.add_argument("--min-available", default="2025-01-01",
                    help="模型带的 available_at 早于此即视为时点过旧，判无法估值")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    args.as_of = evidence_iso_for_signal(args.signal_date)

    usable, stale = latest_model_bands(args.bands, args.min_available, as_of=args.as_of)
    rows = list(csv_rows(args.dossiers))
    header = list(rows[0].keys())
    # v4.54（OI-083）：生产带文件只含池成员；池外档案行（documented_not_attention／boundary 点名档案）
    # 直接从全市场模型带取最新 ok 带——只落档案，不写生产带文件，不进 §9.3。
    archive_codes = {r["security_code"] for r in rows} - set(usable) - set(stale)
    near_zero_div: set[str] = set()   # 银行/保险无已知完整财年分红 → 无法估值
    archive_used: list[str] = []
    if archive_codes and str(args.archive_bands) and args.archive_bands.is_file():
        a_usable, a_stale = latest_model_bands(args.archive_bands, args.min_available,
                                               codes=archive_codes, as_of=args.as_of)
        for c in archive_codes:
            if c in a_usable:
                usable[c] = a_usable[c]; archive_used.append(c)
            elif c in a_stale:
                stale[c] = a_stale[c]
        # 池外银行/保险按信号日的股利与利率计算，与池内同源。
        names = {r["security_code"]: r.get("security_name", "") for r in rows}
        rf = latest_rf(args.signal_date)
        for c in list(archive_used):
            if is_divspread_financial(c, names.get(c, "")):
                v = bank_dividend_intrinsic(c, args.signal_date, rf) if rf is not None else None
                if v:
                    b = dict(usable[c]); b["intrinsic_value"] = f"{v:.4f}"; b["roic_path"] = "bank_divspread"
                    b["exright_note"] = "股利折现口径（分子为最近已知完整财年分红，不折）"; b["forecast_overlay"] = ""
                    usable[c] = b
                else:
                    usable.pop(c, None); archive_used.remove(c); near_zero_div.add(c)
        print(f"  池外档案带（直接取自 {args.archive_bands.name}，不落生产带文件）：可用 {len(archive_used)} 只、"
              f"过旧 {sum(1 for c in archive_codes if c in a_stale)} 只、无带 {len(archive_codes) - len(archive_used) - sum(1 for c in archive_codes if c in a_stale)} 只")
    actions = load_actions()

    applied, kept_unvaluable, kept_stale, action_adj = [], [], [], []
    near_zero: set[str] = set()
    for row in rows:
        code = row["security_code"]
        band = usable.get(code)
        # v4.55：IV 趋零的「ok」带（零增长永续价值≈净负债，判例 云南锗业 IV 0.0003）写成 0.00~0.00 无意义，
        # 按 §6.5.2.4 统一口径判无法估值（与拒绝出带同处理）。
        if band is not None:
            try:
                if float(band.get("intrinsic_value") or 0) < 0.01:
                    band = None
                    stale.pop(code, None)
                    near_zero.add(code)
            except (TypeError, ValueError):
                band = None
        if band is None:
            # v4.22（OI-068 统一口径）：模型给不出新带 → 清空带、判无法估值（下游建带卡→
            # 估值表自动落「无法估值」），不再保留手工带。原带写入 notes 留痕。
            was = f"{row.get('band_low','')}~{row.get('band_high','')}"
            if row.get("band_low") or row.get("band_high"):
                note = f"**{args.as_of} 模型不可估，清空带**：原带 {was} 撤销，判无法估值。"
                row["notes"] = note + ("｜" + row["notes"] if row.get("notes") else "")
            row["band_low"] = row["band_high"] = ""
            row["bespoke"] = "true"
            row["band_derivation"] = "model_unvaluable"
            row["band_method"] = ("无法估值·模型判不可估（§6.5.2.4 统一口径）："
                                  + ("最新 ok 模型带早于时点门槛" if code in stale
                                     else "模型价值趋零（零增长永续价值≈净负债，IV<0.01）" if code in near_zero
                                     else "银行/保险股利折现：无已知完整财年现金分红" if code in near_zero_div
                                     else "模型对各期均拒绝出带"))
            row["decided_by"] = "内在价值模型（§6.5.2.3；模型重新可算后自动回归模型带）"
            row["anchor_earnings_yi"] = ""
            row["reviewed_at"] = args.as_of
            (kept_stale if code in stale else kept_unvaluable).append(row["security_name"])
            continue

        # 已归一化的生产带保持幂等；池外原始模型带按相同事件规则调整到信号日。
        band = dict(band)
        adjusted = exright_normalize(band, actions.get(code, []), args.signal_date)
        iv = float(band["intrinsic_value"])
        if adjusted:
            action_adj.append(row["security_name"])
        old_low, old_high = row["band_low"], row["band_high"]
        old_mid = (float(old_low) + float(old_high)) / 2 if old_low and old_high else None

        row["band_low"] = f"{iv * 0.90:.2f}"
        row["band_high"] = f"{iv * 1.10:.2f}"
        # **`bespoke` 必须保持 `true`**：它的语义是「带只由本档给出，通用十类模型不参与」，
        # 而本档现在装的正是模型带。设成 `false` 会让 `build_valuation_band_cards.py` 走通用路径
        # 把带覆盖掉——2026-08-10 首次落地时正是这么错的，17 只被重算成兜底 EPV 后判无法估值。
        row["bespoke"] = "true"
        # v4.00：带来源分四条路径（§6.5.2.3），派生说明按路径写，不再一律套权益 DCF 的口径
        roic_path = (band.get("roic_path") or "").strip()
        # 被 §6.4 预告/快报叠加过的行**不能再宣称与回测同口径**——回测无历史预告面板。
        overlay = (band.get("forecast_overlay") or "").strip()
        archive_tag = ("**池外档案带**（§6.1：只落档案、不落生产带文件、不进 §9.3；直接取自全市场模型带）｜"
                       if code in archive_used else "")
        if overlay:
            common_head = (
                f"**预告/快报口径（§6.4 叠加，正式报告披露后由机械带取代）**："
                f"报告期 {band['report_date'][:10]}、生效日 {band['available_at'][:10]}"
                f"（{band.get('forecast_source') or overlay}）｜"
                f"**本行与回测 `valuation_ratio` 不同口径**，回测无历史预告面板，"
                f"叠加前 IV {band.get('pre_overlay_iv') or '—'}"
                f"（报告期 {band.get('pre_overlay_report_date') or '—'}）｜")
        else:
            common_head = (archive_tag + f"报告期 {band['report_date'][:10]}、生效日 {band['available_at'][:10]}｜")
        common_tail = (f"**内在价值 {iv:.2f} 元**。带 = IV × [0.90, 1.10]，**中值恰为 IV**，"
                       f"池内 `P/V` 按现价 ÷ V 计算（`scripts/pv_ratio.py`）。")
        def _f(key, fmt="{:.2%}"):
            try:
                return fmt.format(float(band.get(key) or 0))
            except (TypeError, ValueError):
                return "—"
        if roic_path == "bank_divspread":
            row["band_method"] = "银行/保险·股利折现（§6.5.2.3）"
            row["band_derivation"] = (common_head
                + "V = 最近已知完整财年每股现金分红 ÷ (十年国债 + 2%)｜" + common_tail)
        elif roic_path in ("growth", "zero_growth"):
            row["band_method"] = "内在价值模型·ROIC 口径（§6.5.2.3）：NOPAT—投入资本—增量回报—WACC—EV−净负债"
            # g0 的来源按带文件 `roic_g_source` 如实写（hybrid 两腿取大；生产池多数 growth 带由利润增速腿给出，
            # 一律写成「增量ROIC × 再投资率」是 OI-069/OI-076 判例里的错误归因，v4.31 改）
            g_src = (band.get("roic_g_source") or "").strip()
            g_note = {"trailing": "利润增速腿（NOPAT 五年 CAGR）",
                      "capital": "资本腿 min(增量ROIC, 40%) × 再投资率",
                      "none": "两腿皆不可算，按 0"}.get(g_src, "min(增量ROIC, 40%) × 再投资率")
            row["band_derivation"] = (common_head
                + f"每股 NOPAT {band.get('nopat_ps', '—')}｜ROIC0 {_f('roic0')}｜"
                + f"增量 ROIC {_f('incremental_roic')}｜再投资率 {_f('reinvestment_rate')}｜"
                + f"g0 {_f('g0')} = {g_note}｜WACC {_f('wacc')}｜"
                + f"终值 ROIC {_f('roe_terminal')}、g_T {_f('g_terminal')}｜"
                + f"每股净负债 {band.get('net_debt_ps', '—')}｜"
                + ("**零增长永续**（增长输入不可用，V = NOPAT/WACC − 净负债）｜"
                   if roic_path == "zero_growth" else "")
                + common_tail)
        else:
            row["band_method"] = "内在价值模型·权益退路（§6.5.2.3：无三大报表时的权益 DCF）"
            row["band_derivation"] = (common_head
                + f"eps0 {band.get('eps0', '—')}、roe0 {_f('roe0')}（{band.get('roe_source', '')}）｜"
                + f"g0 {_f('g0')} = ROE × 留存率｜r {_f('r')}｜"
                + f"g_T {_f('g_terminal')}、ROE_T {_f('roe_terminal')}｜" + common_tail)
        row["anchor_earnings_yi"] = ""      # 本模型按每股折现，不用亿元口径的利润锚
        row["reviewed_at"] = args.as_of
        row["decided_by"] = "内在价值模型（§6.5.1 模型带）"
        # v4.29：只在带值真的变了才留痕。此前每跑一次就追加一条「原带 X → X（1.00x）」，
        # 272/280 份档案的 notes 被同一句话灌满（判例 2026-08-21：格力/牧原各 20+ 条零信息行），
        # README 第一节随之不可读——留痕的对象是变化，不是跑批次数。
        if (old_low, old_high) != (row["band_low"], row["band_high"]):
            note = (f"**{args.as_of} 模型带更新**：原带 "
                    f"{old_low}~{old_high}" + (f"（中值 {old_mid:.2f}，为新带的 {old_mid / iv:.2f}x）"
                                               if old_mid else "") +
                    f" → {row['band_low']}~{row['band_high']}。")
            row["notes"] = note + ("｜" + row["notes"] if row["notes"] else "")
        applied.append(row["security_name"])

    print(f"档案 {len(rows)} 份｜**改用模型带 {len(applied)} 份**")
    if action_adj:
        print(f"  公司行动归一化 {len(action_adj)} 只：{'、'.join(action_adj)}")
    if kept_unvaluable:
        print(f"  判无法估值·模型不可估 {len(kept_unvaluable)} 只（已清空带）："
              f"{'、'.join(kept_unvaluable)}")
    if kept_stale:
        print(f"  判无法估值·模型带早于 {args.min_available} {len(kept_stale)} 只（已清空带）："
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

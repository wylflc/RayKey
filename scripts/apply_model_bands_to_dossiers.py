#!/usr/bin/env python3
"""把内在价值模型的带写入逐票档案（§6.5.2.3，v2.72 起为唯一带来源）。

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
那是逐票研究的结论，与用哪个模型算带无关，且 §7.4 的复核触发仍要用它。
原带写入 `notes` 留痕，可追溯。

模型给不出新带时的统一口径（v4.22，OI-068，用户 2026-08-19 裁定）
------------------------------------------------------------------
**不再保留手工带**。模型判不可估（亏损、护栏拒绝、零增长价值 ≤ 0）或最新 ok 带早于
`--min-available` 的，一律**清空带并判「无法估值」**——可见、无 `P/V`、不进 §9.3 判定，
模型重新可算后自动回归模型带。唯一例外是 §6.5.2.4 的主体不可比（宏桥型资产注入），
走 `manual_band_overrides.csv` 覆盖表；旧 §6.5.5.2「不得判无法估值、须转逐票推导」
的条款就此废止（它正是 11 只票挂着 2021-2024 年手工带混进档案层的来源）。

用法
----
照 §6.7 建带链跑即可，**两个参数都用缺省**：

    python3 scripts/build_pool_model_bands.py --signal-date YYYY-MM-DD
    python3 scripts/apply_model_bands_to_dossiers.py --signal-date YYYY-MM-DD

随后跑 §6.7 后半段（建带卡 → apply → 校验 → 池物化）。

**不要再往 `data/interim/pool_model_bands.csv` 写带**：那是 v2.72 时代的中间物化文件，
已于 2026-08-17 删除；生产带的唯一落点是 `data/processed/a_share_pool_model_bands_adopted.csv`
（§2 固定产物表）。重建那个旧路径会让两个消费者读到不同的带。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_historical_valuation_bands import load_actions, split_factor  # noqa: E402
from a_share_signal_dates import evidence_iso_for_signal  # noqa: E402
from divspread_names import is_divspread_financial  # noqa: E402  v4.56 银行＋保险股利折现
from screen_daily_volume_price_signals import bank_dividend_intrinsic  # noqa: E402


def latest_rf() -> float | None:
    """十年国债最新值（data/reference/cost_of_equity_inputs.csv 最后一行 risk_free_rate），与 rebuild_bank_bands 同源。"""
    path = ROOT / "data/reference/cost_of_equity_inputs.csv"
    if not path.exists():
        return None
    best = None
    for r in csv.DictReader(path.open(encoding="utf-8")):
        try:
            key = r.get("observed_on") or ""
            if best is None or key > best[0]:
                best = (key, float(r["risk_free_rate"]))
        except (TypeError, ValueError):
            continue
    return best[1] if best else None

DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"


def latest_model_bands(path: Path, min_available: str, codes: set[str] | None = None,
                       as_of: str | None = None) -> tuple[dict, dict]:
    """每只取最新且可用的一条。返回 (可用带, 被时点门槛挡下的)。

    **排序键必须是 `(available_at, report_date)` 两项**：A 股年报与一季报绝大多数在同一天
    披露（4/29-4/30），两条的 `available_at` 因此相等；只比 `available_at` 时严格 `>` 不成立，
    先读到的那条（文件按报告期升序，即**年报**）会留下来，一季报被丢掉。
    2026-08-10 v2.72 首次落地即踩此坑——168 只可比标的中 **59 只用了上一期报告的带**，
    且方向一致偏低（格力电器 108.54 而非 113.07、五粮液 107.30 而非 114.51），
    与回测面板逐票对不上。回测面板本身取值正确，故这**只是生产侧的选择错**，不是口径分歧。
    """
    best: dict[str, dict] = {}
    import roic_inputs
    reset = roic_inputs.load_entity_reset()
    post_seen: set[str] = set()
    if reset:
        for row in csv.DictReader(path.open(newline="", encoding="utf-8-sig")):
            c = row.get("security_code") or ""
            if c in reset and (row.get("report_date") or "") >= reset[c]["reset"] \
                    and (not as_of or (row.get("available_at") or "")[:10] <= as_of):
                post_seen.add(c)
    for row in csv.DictReader(path.open(newline="", encoding="utf-8-sig")):
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
    stale = {c: r for c, r in best.items() if r["available_at"][:10] < min_available}
    return {c: r for c, r in best.items() if c not in stale}, stale


OVERRIDE_PATH = ROOT / "data/processed/manual_band_overrides.csv"


def load_overrides() -> dict[str, dict]:
    if not OVERRIDE_PATH.exists():
        return {}
    with OVERRIDE_PATH.open(encoding="utf-8-sig", newline="") as fh:
        return {(r.get("security_code") or "").strip(): r for r in csv.DictReader(fh)}


def main() -> int:
    ap = argparse.ArgumentParser(description="把内在价值模型的带写入逐票档案")
    # v4.01：缺省改指 §6.7 第①步的采纳产物。旧缺省 data/interim/pool_model_bands.csv 是
    # v2.72 DCF 时代的一次性物化，2026-08-17 曾以缺省身份把 8-10 的陈旧带写回档案（当日发现即修）。
    ap.add_argument("--bands", type=Path,
                    default=ROOT / "data/processed/a_share_pool_model_bands_adopted.csv")
    ap.add_argument("--archive-bands", type=Path, default=ROOT / "data/processed/roic_bands.csv",
                    help="池外档案（L4／boundary 点名档案，§6.1 只落档案）的带来源：生产带文件只含池成员（v4.54，OI-083），"
                         "不在其中的档案行直接从全市场模型带取最新 ok 带；给空串关闭")
    ap.add_argument("--dossiers", type=Path, default=DOSSIERS)
    ap.add_argument("--signal-date", required=True, help="信号日；证据日自动取下一工作日")
    ap.add_argument("--min-available", default="2025-01-01",
                    help="模型带的 available_at 早于此即视为时点过旧，判无法估值（v4.22 统一口径）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    args.as_of = evidence_iso_for_signal(args.signal_date)

    usable, stale = latest_model_bands(args.bands, args.min_available)
    rows = list(csv.DictReader(args.dossiers.open(newline="", encoding="utf-8-sig")))
    header = list(rows[0].keys())
    # v4.54（OI-083）：生产带文件只含池成员；池外档案行（documented_not_attention／boundary 点名档案）
    # 直接从全市场模型带取最新 ok 带——只落档案，不写生产带文件，不进 §9.3。
    archive_codes = {r["security_code"] for r in rows} - set(usable) - set(stale)
    near_zero_div: set[str] = set()   # 银行/保险无已知完整财年分红 → 无法估值
    archive_used: list[str] = []
    if archive_codes and str(args.archive_bands) and args.archive_bands.exists():
        a_usable, a_stale = latest_model_bands(args.archive_bands, args.min_available,
                                               codes=archive_codes, as_of=args.as_of)
        for c in archive_codes:
            if c in a_usable:
                usable[c] = a_usable[c]; archive_used.append(c)
            elif c in a_stale:
                stale[c] = a_stale[c]
        # v4.56（OI-085）：池外档案里的银行/保险同样走股利折现（V = 最近已知完整财年每股现金分红 ÷（十年国债＋2%），
        # 分子口径 divspread_dividend），与池内 build_pool_model_bands 的改写同式；rf 取 cost_of_equity_inputs 最新一行。
        names = {r["security_code"]: r.get("security_name", "") for r in rows}
        rf = latest_rf()
        for c in list(archive_used):
            if is_divspread_financial(c, names.get(c, "")):
                v = bank_dividend_intrinsic(c, args.as_of, rf) if rf is not None else None
                if v:
                    b = dict(usable[c]); b["intrinsic_value"] = f"{v:.4f}"; b["roic_path"] = "bank_divspread"
                    b["exright_note"] = "股利折现口径（分子为最近已知完整财年分红，不折）"; b["forecast_overlay"] = ""
                    usable[c] = b
                else:
                    usable.pop(c, None); archive_used.remove(c); near_zero_div.add(c)
        print(f"  池外档案带（直接取自 {args.archive_bands.name}，不落生产带文件）：可用 {len(archive_used)} 只、"
              f"过旧 {sum(1 for c in archive_codes if c in a_stale)} 只、无带 {len(archive_codes) - len(archive_used) - sum(1 for c in archive_codes if c in a_stale)} 只")
    actions = load_actions()

    OVERRIDES = load_overrides()
    applied, kept_unvaluable, kept_stale, split_adj = [], [], [], []
    near_zero: set[str] = set()
    overridden: list[str] = []
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
            ovr0 = OVERRIDES.get(code)
            if ovr0:
                row["band_low"], row["band_high"] = ovr0["band_low"], ovr0["band_high"]
                row["band_derivation"] = "manual_override"
                row["bespoke"] = "true"
                row["reviewed_at"] = ovr0.get("reviewed_at") or row.get("reviewed_at", "")
                row["band_method"] = (f"§6.5.2.4 人工覆盖（{ovr0.get('reason_code')}）：{ovr0.get('note')}"
                                      f"｜失效条件：{ovr0.get('expires_when')}")
                overridden.append(row.get("security_name") or code)
                continue
            # v4.22（OI-068 统一口径）：模型给不出新带 → 清空带、判无法估值（下游建带卡→
            # 估值表自动落「无法估值」），不再保留手工带。原带写入 notes 留痕。
            was = f"{row.get('band_low','')}~{row.get('band_high','')}"
            if row.get("band_low") or row.get("band_high"):
                note = f"**{args.as_of} 清除手工带（OI-068 统一口径 v4.22）**：原带 {was} 撤销，判无法估值。"
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

        # §6.5.2.4 人工覆盖：模型算得出带、但该带**建立在不可比或已知错误的输入上**时，
        # 仅靠 `bespoke` 保不住手工带——本脚本对有模型带的行是无条件改写的。
        # 判例：宏桥控股 2024 年资产注入 + FY2024/25 的 bps 偏大 10 倍，模型带 0.0974 对现价 19.2。
        # 覆盖表是唯一的例外落点，逐行须写明理由与失效条件。
        ovr = OVERRIDES.get(code)
        if ovr:
            row["band_low"], row["band_high"] = ovr["band_low"], ovr["band_high"]
            row["band_derivation"] = "manual_override"
            row["bespoke"] = "true"
            row["reviewed_at"] = ovr.get("reviewed_at") or row.get("reviewed_at", "")
            row["band_method"] = (f"§6.5.2.4 人工覆盖（{ovr.get('reason_code')}）：{ovr.get('note')}"
                                  f"｜失效条件：{ovr.get('expires_when')}")
            overridden.append(row.get("security_name") or code)
            continue
        # v4.20 起带文件在 `apply_forecast_band_overlay.py` 末段已做**除权归一化**（现金＋送转，
        # `exright_note` 非空即已折算到现价口径，OI-052/OI-039）——此处不得再除一次。
        # 仅当带文件未归一化（绕过 §6.7 链单跑本脚本）时退回旧口径：只折送转、锚在公告日
        # （判例：兴齐眼药 2026-05-22 十送四点五，带 25.80 应为 17.80，`P/V` 1.66 实为 2.41）。
        if (band.get("exright_note") or "").strip():
            factor = 1.0
        else:
            factor = split_factor(actions.get(code, []),
                                  (band.get("bps_basis_date") or "").strip() or band["notice_date"], args.as_of)
        iv = float(band["intrinsic_value"]) / factor
        if factor != 1.0:
            split_adj.append(f"{row['security_name']}÷{factor:g}（带文件未归一化，退旧口径）")
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
                f"差异见 §6.5.2.1｜叠加前 IV {band.get('pre_overlay_iv') or '—'}"
                f"（报告期 {band.get('pre_overlay_report_date') or '—'}）｜")
        else:
            common_head = (archive_tag + f"与 §9.3.1.2 回测所用带**同一套口径**。"
                           f"报告期 {band['report_date'][:10]}、生效日 {band['available_at'][:10]}｜")
        common_tail = (f"**内在价值 {iv:.2f} 元**。带 = IV × [0.90, 1.10]，**中值恰为 IV**，"
                       f"故 `P/V` = 现价 ÷ V（`scripts/pv_ratio.py` 唯一实现）与回测的 `valuation_ratio` 逐位一致。")
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
        row["decided_by"] = "内在价值模型（§6.5.2.3 唯一带来源；v4.00 起 ROIC 口径）"
        # v4.29：只在带值真的变了才留痕。此前每跑一次就追加一条「原带 X → X（1.00x）」，
        # 272/280 份档案的 notes 被同一句话灌满（判例 2026-08-21：格力/牧原各 20+ 条零信息行），
        # README 第一节随之不可读——留痕的对象是变化，不是跑批次数。
        if (old_low, old_high) != (row["band_low"], row["band_high"]):
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
        print(f"  判无法估值·模型不可估 {len(kept_unvaluable)} 只（手工带已清除，v4.22 统一口径）："
              f"{'、'.join(kept_unvaluable)}")
    if kept_stale:
        print(f"  判无法估值·模型带早于 {args.min_available} {len(kept_stale)} 只（手工带已清除）："
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
    if overridden:
        print(f"  §6.5.2.4 人工覆盖 {len(overridden)} 只（见 data/processed/manual_band_overrides.csv）：{'、'.join(overridden)}")
    print(f"  写入 {args.dossiers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

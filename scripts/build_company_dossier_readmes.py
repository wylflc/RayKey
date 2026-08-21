#!/usr/bin/env python3
"""从 a_share_valuation_dossiers.csv 渲染每家公司的 README.md（§6.5.2 主分析文档）。

CSV 是机器可读的唯一真值来源；README 是人读正文，章节顺序固定、不得逐票自由发挥
（§6.5.2「格式统一」）。本脚本把这一条从约定变成可复算的渲染，避免逐份手写产生漂移。

第八节「现价隐含了什么」（v4.30，OI-078）
--------------------------------------
首段由本脚本按**生产带与池内现价**机械生成：`现价 ÷ 生产带中值 = P/V`、带与档位、带所走的
§6.5.1 路径及其增长/折现假设、V 与现价各自对应的归一化盈利倍数。数据与带同源（档案带列 +
`a_share_pool_model_bands_adopted.csv` + 核心池现价），随 §6.7 第 4 步每次重渲染自动更新。
`implied_growth_years` 列只承载**手写的可证伪命题与方法分歧**，不得再写带中枢、隐含年数反解
或任何带值——判例 OI-076① 格力：手写中枢 51 元 vs 生产带 85.29；2026-08-21 清理前 121/280 份
仍含建档时的「本档中枢」。

用法：python3 scripts/build_company_dossier_readmes.py [--check]
  --check 只比对不写盘，有差异时以退出码 1 结束。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from apply_model_bands_to_dossiers import latest_model_bands  # noqa: E402

DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
ADOPTED = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
# 与 apply_model_bands_to_dossiers.py --min-available 缺省一致（§6.5.2.3 时点门槛）
MIN_AVAILABLE = "2025-01-01"

HEADER = """# {name}（{code}）估值档案

> §6.5.2 逐票估值档案**主分析文档**。**目的：确定本公司的合理估值区间，用于判定股价低估/高估程度。**
> 带的机器可读副本在 `data/processed/a_share_valuation_dossiers.csv`（建带引擎只读该 CSV），两者须一致。
> {bespoke_line}
> **更新义务（§7.4.1）**：定期报告／业绩预告快报／研报／高频经营数据／产业政策／技术发布任一变化 →
> 先更新本档、再重算带、并把 `reviewed_at` 改为当日。

| 项 | 值 |
| --- | --- |
| 质量分层 | {tier_line} |
| 行业分类标签 | {tag}（**仅作分类，不再决定估值方法**） |
| 合理价区间 | **{band_low} ~ {band_high}** |
| 估值方法 | {band_method} |
| 盈利锚 | {anchor_line} |
| 本档更新日 | **{reviewed_at}**｜定案：{decided_by} |
"""

FOOTER = """
## 附：证据来源

**结构化证据**：`data/interim/valuation_evidence/<代码>.json`（东财接口：40 期财报、逐份研报一致预期
`ycmx`、业绩预告/快报、历史估值分位；含 `retrieved_at_utc` 与 `source_urls`，可复算）。
**人工取证**：接口不提供的输入（储量、在手订单、管线阶段、分红预案、高频经营数据）由复核者检索后
写入同一 JSON 的 `manual_evidence`（逐条含录入日/类型/期间/标题/来源URL/摘要/用途），每轮抓取结转不清空。
研报逐份跟踪见 `research_ledger.md`（§6.6.1 台账口径，若已建立）。
**v2.07 起不再设 `sources/` 原件目录**——东财无原件下载接口，该机制成文后执行 0 次（§6.5.2）。
"""

BESPOKE_ON = "`bespoke = true`——带只由本档给出，通用十类模型不参与计算。"
BESPOKE_OFF = "`bespoke = false`——本档只补充跟踪指标与复核触发，带仍由通用模型给出。"

PATH_LABEL = {
    "growth": "内在价值模型 ROIC 口径（growth 路径）",
    "zero_growth": "内在价值模型零增长锚（zero_growth 路径）",
    "equity_fallback": "内在价值模型权益退路（equity_fallback 路径）",
    "bank_divspread": "银行股利折现（bank_divspread 路径）",
}
EARNINGS_LABEL = {"growth": "归一化每股 NOPAT", "zero_growth": "归一化每股 NOPAT",
                  "equity_fallback": "归一化 EPS"}
HANDWRITTEN_LABEL = "**手写：可证伪命题与方法分歧**（不作为带；带与 `P/V` 以上段为准）："
PV_RULE = ("`P/V` 高于 1 的部分是市场比模型多付的增长/回报预期，低于 1 则相反；分歧不改带"
           "（§6.5.2.2 档案不得覆盖模型参数），只能由新证据经 §7.4 复核触发重算。")


def bullets(raw: str, seps: str = "；;") -> list[str]:
    """把 CSV 里以 ；/; 分隔的字段拆成条目。"""
    text = (raw or "").strip()
    if not text:
        return []
    for sep in seps[1:]:
        text = text.replace(sep, seps[0])
    return [item.strip() for item in text.split(seps[0]) if item.strip()]


def _num(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _pct(raw, digits: int = 2) -> str:
    val = _num(raw)
    return f"{val:.{digits}%}" if val is not None else "—"


def model_assumptions(band: dict, mid: float, pv: float | None) -> str:
    """第八节第二句：带所走的路径、增长/折现假设、V 与现价各自对应的归一化盈利倍数。

    `implied_pe`/`pe_on_ttm_eps` 是建带时按**除权归一化前**的 V 算的（V_pre ÷ 归一化每股盈利）；
    归一化后 V = V_pre ÷ factor − cash（`exright_factor`/`exright_cash`），每股盈利同除 factor，
    故现价口径的倍数 = 文件值 × V ÷ (V + cash)，factor 自行约掉。
    """
    path = (band.get("roic_path") or "").strip()
    overlay = (band.get("forecast_overlay") or "").strip()
    head = f"生产带按 §6.5.1 唯一口径由{PATH_LABEL.get(path, path or '—')}给出"
    if overlay in ("forecast", "express"):
        head += "（§6.4 预告/快报叠加行，正式报告披露后由机械带取代）"
    if path == "bank_divspread":
        tail = "：V = 近 12 个月每股现金分红 ÷（十年国债 + 2%）"
        if pv:
            tail += f"，即现价股息率 = 带口径要求收益率 ÷ {pv:.3f}"
        return head + tail + "；参数全文见第二节。"
    if path == "growth":
        # g0 的来源按带文件 `roic_g_source` 如实写：hybrid 两腿取大，多数带由利润增速腿给出
        # （§12.99.1：生产池 202 只 growth 带里 116 只），写成「增量 ROIC × 再投资率」是错的归因（OI-069 判例）。
        src = (band.get("roic_g_source") or "").strip()
        capital_leg = (f"资本腿 增量 ROIC {_pct(band.get('incremental_roic'))} × "
                       f"再投资率 {_pct(band.get('reinvestment_rate'))}")
        if src == "trailing":
            g_note = f"利润增速腿＝NOPAT 五年 CAGR，高于{capital_leg}"
        elif src == "capital":
            g_note = capital_leg
        elif src == "none":
            g_note = "两腿皆不可算，按 0 增长"
        else:
            g_note = capital_leg
        params = (f"g0 {_pct(band.get('g0'))}（{g_note}）、WACC {_pct(band.get('wacc'))}、"
                  f"终值占比 {_pct(band.get('terminal_share'), 1)}")
    elif path == "zero_growth":
        params = f"零增长永续 V = 每股 NOPAT ÷ WACC − 每股净负债，g0 0、WACC {_pct(band.get('wacc'))}"
    elif path == "equity_fallback":
        payout = _num(band.get("payout"))
        params = (f"g0 {_pct(band.get('g0'))} = roe0 {_pct(band.get('roe0'))} × "
                  + (f"(1 − 派息率 {payout:.0%})" if payout is not None else "留存率")
                  + f"、r {_pct(band.get('r'))}、终值占比 {_pct(band.get('terminal_share'), 1)}")
    else:
        params = "参数见第二节"
    text = head + "：" + params
    implied_pe, pe_ttm = _num(band.get("implied_pe")), _num(band.get("pe_on_ttm_eps"))
    if implied_pe and path in EARNINGS_LABEL:
        cash = _num(band.get("exright_cash")) or 0.0
        scale = mid / (mid + cash) if mid + cash > 0 else 1.0
        model_pe = implied_pe * scale
        text += f"；V 对应{EARNINGS_LABEL[path]} {model_pe:.1f}×"
        if pe_ttm:
            text += f"（TTM EPS {pe_ttm * scale:.1f}×）"
        if pv:
            text += f"，现价对应 {pv * model_pe:.1f}×"
            if pe_ttm:
                text += f"（TTM {pv * pe_ttm * scale:.1f}×）"
    return text + "；参数全文见第二节。"


def implied_lead(row: dict, meta: dict, band: dict | None) -> tuple[str, bool]:
    """第八节机械首段。返回 (文本, 是否因 IV 与档案中值不符而略去模型参数)。"""
    low, high = _num(row.get("band_low")), _num(row.get("band_high"))
    price, as_of = _num(meta.get("valuation_price")), (meta.get("valuation_price_as_of") or "").strip()
    if low is None or high is None:
        reason = (row.get("band_method") or "模型判不可估").strip()
        if reason.startswith("无法估值·"):
            reason = reason[len("无法估值·"):]
        text = f"**无法估值**——{reason}。"
        if price:
            text += f"现价 {price:g}（{as_of}）；"
        text += "无带、无 `P/V`，不进 §9.3 判定；模型重新可算后自动回归模型带（§6.5.2.4）。"
        return text, False
    mid = (low + high) / 2
    manual = (row.get("band_derivation") or "").strip() == "manual_override"
    band_name = "人工覆盖带" if manual else "生产带"
    if price:
        pv = price / mid
        text = (f"现价 {price:g}（{as_of}）÷ {band_name}中值 V {mid:.2f} = **{pv:.3f}**"
                f"（带 {low:.2f}~{high:.2f}，档位{meta.get('valuation_tier') or '—'}）。")
    else:
        pv = None
        text = (f"{band_name} {low:.2f}~{high:.2f}（中值 V {mid:.2f}）；本档当前不在核心池估值表内，"
                "无现价口径与 `P/V`，不进 §9.3 判定。")
    if manual:
        return text + "带为 §6.5.2.4 人工覆盖（推导与失效条件见第二节）。", False
    skipped = False
    if band is not None:
        iv = _num(band.get("intrinsic_value"))
        if iv is not None and abs(iv - mid) <= 0.005 * mid:
            text += model_assumptions(band, mid, pv)
        else:
            skipped = True
    if pv:
        text += PV_RULE
    return text, skipped


def render(row: dict, pool: dict, bands: dict) -> tuple[str, bool]:
    code = row["security_code"]
    meta = pool.get(code, {})
    tier = meta.get("quality_tier", "")
    score = meta.get("quality_score", "")
    tier_line = f"{tier}（参考分 {score}）" if tier and score else (tier or "—")
    anchor = (row.get("anchor_earnings_yi") or "").strip()
    anchor_line = f"{anchor} 亿元" if anchor else "—（非盈利口径）"

    parts = [HEADER.format(
        name=row["security_name"],
        code=code,
        bespoke_line=BESPOKE_ON if str(row.get("bespoke", "")).strip().lower() == "true" else BESPOKE_OFF,
        tier_line=tier_line,
        tag=meta.get("strategy_tag", "—"),
        band_low=row["band_low"],
        band_high=row["band_high"],
        band_method=row["band_method"],
        anchor_line=anchor_line,
        reviewed_at=row["reviewed_at"],
        decided_by=row["decided_by"],
    )]

    notes = (row.get("notes") or "").strip()
    if notes:
        parts.append(f"\n## 一、为什么脱离通用模型\n\n{notes}\n")
    parts.append(f"\n## 二、带的推导（须可复算）\n\n{row['band_derivation'].strip()}\n")

    override = (row.get("runrate_override_reason") or "").strip()
    if override:
        parts.append(f"\n## 三、§6.5.4 运行率不变量\n\n{override}\n")

    sections = [
        ("四、下一个业绩核对点", row.get("next_earnings_check"), "；;"),
        ("五、高频/行业跟踪指标（不进财报但决定结论）", row.get("hf_indicators"), "｜|"),
        ("六、财务跟踪指标", row.get("key_metrics"), ";；"),
        ("七、复核触发条件", row.get("review_triggers"), "；;"),
    ]
    for title, raw, seps in sections:
        items = bullets(raw, seps)
        if not items:
            continue
        parts.append(f"\n## {title}\n\n" + "\n".join(f"- {item}" for item in items) + "\n")

    lead, skipped = implied_lead(row, meta, bands.get(code))
    parts.append(f"\n## 八、现价隐含了什么\n\n{lead}\n")
    implied = (row.get("implied_growth_years") or "").strip()
    if implied:
        parts.append(f"\n{HANDWRITTEN_LABEL}{implied}\n")

    parts.append(FOOTER)
    return "".join(parts), skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只比对不写盘")
    args = parser.parse_args()

    with POOL.open(encoding="utf-8-sig") as handle:
        pool = {r["security_code"]: r for r in csv.DictReader(handle)}
    with DOSSIERS.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    bands: dict[str, dict] = {}
    if ADOPTED.exists():
        bands, _stale = latest_model_bands(ADOPTED, MIN_AVAILABLE)
    else:
        print(f"  ⚠ 缺 {ADOPTED.relative_to(ROOT)}，第八节只按档案带渲染、不写模型参数")

    changed, missing_dir, param_skipped = [], [], []
    for row in rows:
        target = ROOT / (row.get("dossier_dir") or "").strip()
        if not row.get("dossier_dir"):
            missing_dir.append(row["security_code"])
            continue
        target.mkdir(parents=True, exist_ok=True)
        path = target / "README.md"
        text, skipped = render(row, pool, bands)
        if skipped:
            param_skipped.append(row["security_code"])
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            changed.append(row["security_code"])
            if not args.check:
                path.write_text(text, encoding="utf-8")

    print(f"档案 {len(rows)} 份，{'需更新' if args.check else '已写入'} {len(changed)} 份")
    if changed:
        print("  " + " ".join(changed[:40]) + (" …" if len(changed) > 40 else ""))
    if param_skipped:
        print(f"  ⚠ 第八节略去模型参数（带文件 IV 与档案中值不符，档案未随 §6.7 第 4 步更新？）"
              f"{len(param_skipped)} 份：{' '.join(param_skipped)}")
    if missing_dir:
        print(f"  ❌ 缺 dossier_dir：{' '.join(missing_dir)}")
        return 1
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())

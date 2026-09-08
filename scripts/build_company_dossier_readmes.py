#!/usr/bin/env python3
"""从档案、分层与生产带渲染公司 README。

当前估值与研究记录分别显示；模型更新不改变研究证据日期。
--check 只比对不写盘，有漂移时非零退出。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pv_ratio import trading_pv  # noqa: E402  v4.62 OI-091
from apply_model_bands_to_dossiers import latest_model_bands  # noqa: E402

DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
ADOPTED = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
TRIAGE_CLASS: dict[str, str] = {}   # v4.54（OI-083）：分层/标签改读分层表，池外档案（L4／boundary）同样可得
# 与 apply_model_bands_to_dossiers.py --min-available 缺省一致（§6.5.2.3 时点门槛）
MIN_AVAILABLE = "2025-01-01"

HEADER = """# {name}（{code}）估值档案

> 当前带由工作流程的模型链生成，本页从结构化档案渲染。
> 估值更新不代表研究指标、判断或触发条件已重新核验；研究更新按证据日期记录。

| 项 | 值 |
| --- | --- |
| 质量分层 | {tier_line} |
| 质量证据日 | {quality_evidence_date} |
| 研究策略标签 | {tag} |
| 合理价区间 | **{band_low} ~ {band_high}** |
| 估值方法 | {band_method} |
| 估值更新日 | **{reviewed_at}** |
"""

FOOTER = """
## 附：证据与记录

- 结构化档案：`data/processed/a_share_valuation_dossiers.csv`，按证券代码检索；`notes` 保留历史带变更与建档来源。
- 财务与研报证据：`data/interim/valuation_evidence/<代码>.json`，核对来源与抓取时间；人工证据写入其 `manual_evidence`。
- 名单、质量及复核时间：工作流程列明的三类表与分层表；旧结论按决策日志追溯。
"""

PATH_LABEL = {
    "growth": "内在价值模型 ROIC 口径（growth 路径）",
    "zero_growth": "内在价值模型零增长锚（zero_growth 路径）",
    "equity_fallback": "内在价值模型权益退路（equity_fallback 路径）",
    "bank_divspread": "银行/保险股利折现（bank_divspread 路径）",
}
EARNINGS_LABEL = {"growth": "归一化每股 NOPAT", "zero_growth": "归一化每股 NOPAT",
                  "equity_fallback": "归一化 EPS"}
HANDWRITTEN_LABEL = "研究备注原文（须按证据日期复核，不作为现行估值或交易依据）"
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
        tail = "：V = 最近已知完整财年每股现金分红 ÷（十年国债 + 2%）"
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
    band_name = "模型带" if band is not None else "档案模型带"
    if price:
        pv = trading_pv(price, band) if band is not None else None
        if pv is None:
            pv = price / mid
        text = (f"现价 {price:g}（{as_of}）÷ {band_name}中值 V {mid:.2f} = **{pv:.3f}**"
                f"（带 {low:.2f}~{high:.2f}）。")
    else:
        pv = None
        text = (f"{band_name} {low:.2f}~{high:.2f}（中值 V {mid:.2f}）；本档当前不在核心池估值表内，"
                "无现价口径与 `P/V`，不进 §9.3 判定。")
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


def render(row: dict, pool: dict, bands: dict, tiers: dict | None = None) -> tuple[str, bool]:
    code = row["security_code"]
    meta = pool.get(code, {})
    tmeta = (tiers or {}).get(code, {})
    tier = tmeta.get("quality_tier") or meta.get("quality_tier", "")
    tri_class = TRIAGE_CLASS.get(code, "")
    if tri_class in ("boundary_pending", "garbage"):
        tier = ""
    score = tmeta.get("quality_score") or meta.get("quality_score", "")
    if tier and score:
        tier_line = f"{tier}（参考分 {score}）"
    elif tier:
        tier_line = tier
    else:
        # 池外且无分层行（boundary_pending 点名档案）：按三类表写明类别，不评分是 §5.7 硬规则 1
        tri_class = (TRIAGE_CLASS or {}).get(code, "")
        tier_line = f"{tri_class}（不评分）" if tri_class else "—"
    parts = [HEADER.format(
        name=row["security_name"],
        code=code,
        tier_line=tier_line,
        quality_evidence_date=tmeta.get("evidence_available_at") or "未记录",
        tag=meta.get("strategy_tag") or tmeta.get("primary_strategy_tag") or "—",
        band_low=row["band_low"],
        band_high=row["band_high"],
        band_method=row["band_method"],
        reviewed_at=row["reviewed_at"],
    )]

    derivation = row['band_derivation'].strip()
    derivation = derivation.replace("与 §9.3.1.2 回测所用带**同一套口径**。", "")
    derivation = derivation.replace("故 `P/V` = 现价 ÷ V（`scripts/pv_ratio.py` 唯一实现）与回测的 `valuation_ratio` 逐位一致。",
                                    "池内 `P/V` 按现价 ÷ V 计算；交易资格按工作流程判定。")
    parts.append(f"\n## 二、模型推导\n\n{derivation}\n")
    parts.append("\n> 以下为留存研究记录；本次估值更新未重新核验这些指标与复核时点。\n")

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
        parts.append(f"\n<details>\n<summary>{HANDWRITTEN_LABEL}</summary>\n\n{implied}\n\n</details>\n")

    parts.append(FOOTER)
    return "".join(parts), skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只比对不写盘")
    args = parser.parse_args()

    with POOL.open(encoding="utf-8-sig") as handle:
        pool = {r["security_code"]: r for r in csv.DictReader(handle)}
    if TRIAGE.exists():
        with TRIAGE.open(encoding="utf-8-sig") as handle:
            TRIAGE_CLASS.update({r["security_code"]: r.get("attention_class", "") for r in csv.DictReader(handle)})
    tiers: dict[str, dict] = {}
    if TIERS.exists():
        with TIERS.open(encoding="utf-8-sig") as handle:
            tiers = {r["security_code"]: r for r in csv.DictReader(handle)}
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
        text, skipped = render(row, pool, bands, tiers)
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

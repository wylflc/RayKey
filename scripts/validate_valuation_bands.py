#!/usr/bin/env python3
"""Validate that every fair-price band was built by a strategy model (§6.5/§6.6).

This is the enforcement half of workflow v1.28. The written standard alone does
not survive a change of model or agent — what survives is a mechanical check
that a band can be **recomputed** from its declared inputs, plus the rule that a
band which cannot be recomputed does not confer buy eligibility (§6.7 要求 10/11).

The check that matters is the direction of causation (§6.6 分工恒等式)::

    带 = 模型(锚定量, 倍数)     ← only §7 review changes it
    档 = 位置(现价, 带)         ← daily, §6.2.1.6
    任何时候不得由档反推带。

A band back-solved from an already-judged tier makes the daily auto-tiering
circular (``档 = 位置(现价, 反推(档))``) and silently turns the §14 trim ladder
into a cost anchor. Legacy rows of exactly that shape are detected here by
recomputing them against the undocumented ladder they used, so the migration
list is produced from evidence rather than from trust.

Six checks (§6.7 要求 10):

1. 建带卡五槽非空
2. ``anchor_metric`` ↔ ``strategy_tag`` mapping legal (§6.5.2)
3. ``band_low_coef`` / ``band_high_coef`` equal the type-table values
4. recomputed band within ±2% of the stored band (§6.5.1 two shapes)
5. ``multiple_or_rate`` inside the §6.5.4 allowed range
6. ``band_derivation == "model"``
7. §6.5.6 成长期权的五条硬约束（仅当该票计入了期权时生效）

Rows failing any check go to ``valuation_rebuild_queue.csv``, ordered
持仓 → 当前可买 → 其余 (§6.7 要求 11).

Usage::

    python3 scripts/validate_valuation_bands.py --as-of 2026-08-01
    python3 scripts/validate_valuation_bands.py --as-of 2026-08-01 --strict
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_QUEUE = ROOT / "data/interim/valuation_rebuild_queue.csv"

BAND_TOLERANCE = 0.02  # §6.7 要求 10 第 4 项

# --- §6.5.2 类型表：标签 → (锚定量枚举, 形态, 带系数) -------------------------
# 形态1 倍数型：合理值 = anchor × multiple；带 = 合理值 × [low, high]
# 形态2 收益率型：带 = anchor ÷ [rate_high, rate_low]，带系数不参与（记 None）
TYPE_TABLE: dict[str, dict] = {
    "A": {
        "name": "现金流复利型",
        "anchors": {"annual_distributable_cash": 2, "normalized_profit": 1},
        # v1.30 (OI-004)：A-2 的锚是自身历史交易水平，系数按质量分层分档。
        # 其余类型的锚已是正常化/偏乐观口径，系数不随分层变动。
        "coefs": {"normalized_profit": {"L1": (0.90, 1.15), "L2": (0.85, 1.05), "L3": (0.80, 1.00)}},
    },
    "C": {
        "name": "GARP成长型",
        "anchors": {"normalized_profit": 1, "realized_growth_profit": 1, "repaired_normalized_profit": 1, "bvps": 1, "forward_normalized_profit": 1},
        "coefs": {"normalized_profit": {"L1": (0.90, 1.15), "L2": (0.85, 1.05), "L3": (0.80, 1.00)}, "realized_growth_profit": (1.0, 1.5), "repaired_normalized_profit": (0.85, 1.00), "bvps": (0.85, 1.00), "forward_normalized_profit": (1.0, 1.5)},  # 带系数即 PEG 带
    },
    "D": {
        "name": "产业链爆发/关键瓶颈型",
        "anchors": {"normalized_profit": 1, "bvps": 1, "normalized_profit_2_3y": 1},
        "coefs": {"normalized_profit": (0.80, 1.00), "bvps": (0.85, 1.00), "normalized_profit_2_3y": (0.80, 1.00)},
    },
    "E": {
        "name": "落难白马型",
        "anchors": {"bvps": 1, "repaired_normalized_profit": 1},
        "coefs": {"bvps": (0.85, 1.00), "repaired_normalized_profit": (0.85, 1.00)},
    },
    "F": {
        "name": "资源NAV型",
        "anchors": {"mid_cycle_profit": 1, "bvps": 1, "resource_nav": 1},
        "coefs": {"mid_cycle_profit": (0.85, 1.00), "bvps": (0.85, 1.00), "resource_nav": (0.85, 1.00)},
    },
    "H": {
        "name": "成本曲线周期型",
        "anchors": {"bvps": 1, "mid_cycle_ebitda": 1, "mid_cycle_profit": 1},
        # 成本曲线分位前 25% 可取 (0.90, 1.05)；两组均合法，见 §6.5.2
        "coefs": {"bvps": (0.85, 1.00), "mid_cycle_ebitda": [(0.85, 1.00), (0.90, 1.05)],
                  "mid_cycle_profit": [(0.85, 1.00), (0.90, 1.05)]},
    },
    "J": {
        "name": "金融资本型",
        "anchors": {"bvps": 1},
        "coefs": {"bvps": (0.90, 1.10)},
    },
    "K": {
        "name": "稳态现金分配型",
        "anchors": {"normalized_profit": 1, "bvps": 1, "dps": 2},
        "coefs": {"normalized_profit": {"L1": (0.90, 1.15), "L2": (0.85, 1.05), "L3": (0.80, 1.00)}, "bvps": (0.85, 1.00), },
    },
    "M": {
        "name": "管线/研发资产型",
        "anchors": {"forward_normalized_profit": 1, "bvps": 1, "sotp_value": 1},
        "coefs": {"forward_normalized_profit": (0.80, 1.00), "bvps": (0.85, 1.00), "sotp_value": (0.80, 1.00)},
    },
    "N": {
        "name": "订阅/递延收入型",
        "anchors": {"bvps": 1, "epv_profit": 1},
        "coefs": {"bvps": (0.85, 1.00), "epv_profit": (0.85, 1.00)},
    },
    "P": {
        "name": "在手订单兑现型",
        "anchors": {"forward_normalized_profit": 1, "bvps": 1, "backlog_annual_profit": 1},
        "coefs": {"forward_normalized_profit": (0.80, 1.00), "bvps": (0.85, 1.00), "backlog_annual_profit": (0.80, 1.00)},
    },
}

RETIRED_TAGS = {"B": "清算价值地板（通用校验一）", "G": "股东回报上限（通用校验二）"}

MULTIPLE_SOURCES = {
    "own_history_median",
    "peer_median",
    "required_return",
    "gordon",
    "implied_pb",
    "rnpv_table",
    "doc_table",
}

# --- §6.5.4 参数允许区间（只校验可机械判定的几项）---------------------------
# g/COE/r 的上下限；PE 的分位约束需要历史序列，留给估值执行侧，本脚本不校验。
RATE_LIMITS = {
    "K": (0.030 - 0.035, 0.045),  # r − g 的可能范围（r 3.0%-4.5%，g ≤ 3.5%）
    "A": (0.06 - 0.04, 0.08),     # rate = [6%−g, 8%−g]，g ≤ 4%
}
MAX_PERPETUAL_G = 0.035

# --- §6.5.6 成长期权：证据等级 → 实现概率上限 -------------------------------
GROWTH_OPTION_PROB_CAP = {0: 0.00, 1: 0.10, 2: 0.20, 3: 0.35, 4: 0.50, 5: 0.60}
GROWTH_OPTION_MAX_SHARE = 0.50          # 期权价值 ÷ base 带中值
GROWTH_OPTION_TIERS = {"L1", "L2"}      # 仅 L1/L2 可计入

CARD_SLOTS = [
    "anchor_metric",
    "anchor_value",
    "anchor_scope",
    "anchor_basis",
    "multiple_or_rate",
    "multiple_source",
    "band_low_coef",
    "band_high_coef",
    "band_derivation",
    "band_sensitivity",
]

# 存量档位反推带使用的未成文系数阶梯（v1.28 前）。只用于**识别**历史反推行，
# 不是任何标准；识别到即判 fallback（§6.7 要求 11）。
LEGACY_TIER_LADDER = {
    "低估": (1.30, 1.70),
    "较低估": (1.12, 1.40),
    "中性": (0.88, 1.12),
    "较高估": (0.78, 0.95),
    "高估": (0.50, 0.78),
}
LEGACY_BASIS_RE = re.compile(r"按(低估|较低估|中性|较高估|高估)档标准带")


def to_float(value: object) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def parse_rate_range(text: str) -> tuple[float, float] | None:
    """形态2 的 ``multiple_or_rate`` 填 ``rate_low~rate_high``（小数或百分数）。"""
    parts = re.split(r"[~～]", str(text).strip())
    if len(parts) != 2:
        return None
    lo, hi = to_float(parts[0].rstrip("%")), to_float(parts[1].rstrip("%"))
    if lo is None or hi is None:
        return None
    if "%" in str(text):
        lo, hi = lo / 100, hi / 100
    if lo <= 0 or hi <= 0 or lo > hi:
        return None
    return lo, hi


def tag_letter(strategy_tag: str) -> str:
    text = str(strategy_tag).strip()
    return text[0].upper() if text else ""


def detect_legacy_fallback(row: dict) -> str | None:
    """Return the ladder tier if the band is a fixed multiple of 估值当日现价."""
    basis = str(row.get("fair_price_basis", "") or "")
    match = LEGACY_BASIS_RE.search(basis)
    if not match:
        return None
    low, high = to_float(row.get("fair_price_low")), to_float(row.get("fair_price_high"))
    price = to_float(row.get("current_price")) or to_float(row.get("valuation_price"))
    if None in (low, high, price) or not price:
        return match.group(1)
    coef_low, coef_high = LEGACY_TIER_LADDER[match.group(1)]
    reproduced = (
        abs(low / price / coef_low - 1) <= BAND_TOLERANCE
        and abs(high / price / coef_high - 1) <= BAND_TOLERANCE
    )
    return f"{match.group(1)}（精确复算为 {coef_low}-{coef_high}×估值当日现价）" if reproduced else match.group(1)


def recompute_band(row: dict, shape: int) -> tuple[float, float] | None:
    """§6.5.1 两种形态的复算。返回 (low, high) 或 None（输入不全）。"""
    anchor = to_float(row.get("anchor_value"))
    if anchor is None:
        return None
    scope = str(row.get("anchor_scope", "") or "").strip()
    shares = to_float(row.get("shares_out"))
    if scope == "market_cap":
        if not shares:
            return None
        divisor = shares
    elif scope == "per_share":
        divisor = 1.0
    else:
        return None

    if shape == 2:
        rates = parse_rate_range(row.get("multiple_or_rate", ""))
        if not rates:
            return None
        rate_low, rate_high = rates
        return anchor / rate_high / divisor, anchor / rate_low / divisor

    multiple = to_float(row.get("multiple_or_rate"))
    coef_low = to_float(row.get("band_low_coef"))
    coef_high = to_float(row.get("band_high_coef"))
    if None in (multiple, coef_low, coef_high):
        return None
    fair = anchor * multiple
    return fair * coef_low / divisor, fair * coef_high / divisor


def check_growth_option(row: dict) -> list[str]:
    """§6.5.6 成长期权的硬约束。未计入期权（值为空或 0）时返回空。

    单位约定：``growth_option_value`` 与 ``base_band_low/high``、``fair_price_low/high``
    同为**每股口径（元/股）**。期权按市值算出后须除以 ``shares_out`` 再入库，
    否则 ``growth_option_share`` 会把市值除以股价、量纲不一致（自测已命中该错）。
    """
    problems: list[str] = []
    value = to_float(row.get("growth_option_value"))
    if not value:
        return problems

    quality = str(row.get("quality_tier", "") or "").strip().upper()
    if quality and quality not in GROWTH_OPTION_TIERS:
        problems.append(f"检查7 成长期权仅 L1/L2 可用，本行为 {quality}（§6.5.6 硬约束 1）")

    level = to_float(row.get("growth_option_evidence_level"))
    prob = to_float(row.get("growth_option_probability"))
    if level is None:
        problems.append("检查7 计入期权但缺 growth_option_evidence_level")
    else:
        cap = GROWTH_OPTION_PROB_CAP.get(int(level))
        if cap is None:
            problems.append(f"检查7 证据等级 {level} 不在 §5.4-D 的 0-5 范围")
        elif cap == 0:
            problems.append("检查7 证据等级 0（传闻/概念）不得计入期权（§6.5.6 概率表）")
        elif prob is None:
            problems.append("检查7 计入期权但缺 growth_option_probability")
        elif prob > cap + 1e-9:
            problems.append(f"检查7 实现概率 {prob:.0%} 超过证据等级 {int(level)} 的上限 {cap:.0%}")

    base_low, base_high = to_float(row.get("base_band_low")), to_float(row.get("base_band_high"))
    if None in (base_low, base_high):
        problems.append("检查7 计入期权但缺 base_band_low/base_band_high（§6.5.6 硬约束 3：两条带都必须展示）")
    else:
        base_mid = (base_low + base_high) / 2
        share = to_float(row.get("growth_option_share"))
        if base_mid > 0:
            implied = value / base_mid
            if share is not None and abs(share - implied) > 0.02:
                problems.append(f"检查7 growth_option_share {share:.2f} 与复算值 {implied:.2f} 不符")
            if implied > GROWTH_OPTION_MAX_SHARE and str(row.get("band_fragile", "")).strip().lower() not in {"true", "1", "yes"}:
                problems.append(
                    f"检查7 期权占比 {implied:.0%} > 50% 上限，须置 band_fragile=true 并按 §6.5.5 降一档"
                )

    if not str(row.get("growth_option_milestones", "") or "").strip():
        problems.append("检查7 计入期权但缺 growth_option_milestones（§6.5.6 硬约束 4：衰减机制的判据）")

    return problems


def check_row(row: dict) -> tuple[list[str], str]:
    """Return (violated checks, severity).

    ``blocking``  the band itself is not a model band (back-solved from a tier,
                  illegal tag, coefficients or recomputation off). §6.7 要求 11
                  demotes these to 可持有.
    ``backfill``  the band looks like a model band but the v1.28 card fields
                  have not been written yet. That is a registration lag, not a
                  missing band — the same distinction v1.25/v1.26 drew for
                  割肉价登记时滞 and 伪欠账. Time-bound obligation, does not
                  block buying (§10.4 研究档案项同构).
    """
    problems: list[str] = []
    letter = tag_letter(row.get("strategy_tag", ""))

    if letter in RETIRED_TAGS:
        problems.append(f"检查2 标签 {letter} 自 v1.28 起不是主标签（已降为{RETIRED_TAGS[letter]}），须按 §6.5.0 重贴")
        return problems, "blocking"
    spec = TYPE_TABLE.get(letter)
    if spec is None:
        problems.append(f"检查2 未知策略标签 {letter or '(空)'}，不在 §6.5.2 类型表内")
        return problems, "blocking"

    # 检查 1：建带卡五槽非空
    missing = [slot for slot in CARD_SLOTS if not str(row.get(slot, "") or "").strip()]
    if missing:
        problems.append("检查1 建带卡缺槽：" + "/".join(missing))

    # 检查 6：band_derivation
    derivation = str(row.get("band_derivation", "") or "").strip()
    legacy = detect_legacy_fallback(row)
    if derivation == "fallback" or (not derivation and legacy):
        problems.append(f"检查6 band_derivation=fallback（档位反推带{'，' + legacy if legacy else ''}）")
    elif derivation and derivation != "model":
        problems.append(f"检查6 band_derivation 非法值 '{derivation}'（只允许 model/fallback）")

    anchor_metric = str(row.get("anchor_metric", "") or "").strip()
    if anchor_metric:
        # 检查 2：锚定量与标签的映射
        if anchor_metric not in spec["anchors"]:
            problems.append(
                f"检查2 {letter} 的 anchor_metric 只允许 {sorted(spec['anchors'])}，实为 '{anchor_metric}'"
            )
        else:
            shape = spec["anchors"][anchor_metric]

            # 检查 3：带系数等于类型表规定值（形态2 不适用）
            if shape == 1:
                allowed = spec["coefs"].get(anchor_metric)
                if isinstance(allowed, dict):          # 按质量分层分档（A-2，v1.30）
                    tier = str(row.get("quality_tier", "") or "").strip().upper()
                    allowed_sets = [allowed[tier]] if tier in allowed else list(allowed.values())
                    if tier not in allowed:
                        problems.append(f"检查3 A-2 带系数按分层分档，但 quality_tier='{tier}' 不在 L1/L2/L3")
                else:
                    allowed_sets = allowed if isinstance(allowed, list) else [allowed]
                got = (to_float(row.get("band_low_coef")), to_float(row.get("band_high_coef")))
                if None in got:
                    problems.append("检查3 带系数缺失")
                elif not any(
                    abs(got[0] - a[0]) < 1e-9 and abs(got[1] - a[1]) < 1e-9 for a in allowed_sets
                ):
                    problems.append(f"检查3 带系数 {got} 不等于 §6.5.2 规定值 {allowed_sets}")

            # 检查 4：复算带与入库带偏差 ≤2%
            stored = (to_float(row.get("fair_price_low")), to_float(row.get("fair_price_high")))
            recomputed = recompute_band(row, shape)
            if recomputed is None:
                problems.append("检查4 复算输入不全（anchor_value/anchor_scope/shares_out/multiple_or_rate）")
            elif None in stored:
                problems.append("检查4 入库带缺失")
            else:
                dev_low = abs(recomputed[0] / stored[0] - 1) if stored[0] else 1.0
                dev_high = abs(recomputed[1] / stored[1] - 1) if stored[1] else 1.0
                if max(dev_low, dev_high) > BAND_TOLERANCE:
                    problems.append(
                        f"检查4 复算带 {recomputed[0]:.4g}-{recomputed[1]:.4g} 与入库带 "
                        f"{stored[0]:.4g}-{stored[1]:.4g} 偏差 {max(dev_low, dev_high):.1%} > 2%"
                    )

            # 检查 5：倍数/折现率落在 §6.5.4 允许区间
            source = str(row.get("multiple_source", "") or "").strip()
            if source and source not in MULTIPLE_SOURCES:
                problems.append(f"检查5 multiple_source 非法值 '{source}'，允许 {sorted(MULTIPLE_SOURCES)}")
            if shape == 2:
                rates = parse_rate_range(row.get("multiple_or_rate", ""))
                limits = RATE_LIMITS.get(letter)
                if rates and limits and not (limits[0] <= rates[0] <= limits[1] and limits[0] <= rates[1] <= limits[1]):
                    problems.append(
                        f"检查5 rate {rates[0]:.3f}~{rates[1]:.3f} 超出 §6.5.4 区间 {limits[0]:.3f}~{limits[1]:.3f}"
                    )
            g_value = to_float(row.get("perpetual_growth"))
            if g_value is not None and g_value > MAX_PERPETUAL_G:
                problems.append(f"检查5 永续增长 g={g_value:.3f} > 3.5% 上限（硬拦截）")

    # 检查 7：成长期权硬约束（§6.5.6）
    problems.extend(check_growth_option(row))

    if not problems:
        return problems, "ok"

    # 只缺建带卡字段、且带本身不是档位反推的 → 登记欠账，不阻断买入。
    only_missing_card = all(p.startswith("检查1") for p in problems)
    severity = "backfill" if (problems and only_missing_card and not legacy) else "blocking"
    # 阻断原因排在前面：缺卡（检查1）几乎所有存量行都有，排在首位会掩盖真正的阻断项。
    problems.sort(key=lambda p: p.startswith("检查1"))
    return problems, severity


def load_codes(path: Path, column: str = "security_code") -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig") as handle:
        return {str(r.get(column, "")).strip() for r in csv.DictReader(handle) if r.get(column)}


def main() -> int:
    parser = argparse.ArgumentParser(description="校验合理价区间是否由策略模型算出（工作流 §6.7 要求 10）")
    parser.add_argument("--valuation", type=Path, default=DEFAULT_VALUATION)
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS)
    parser.add_argument("--queue-out", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--strict", action="store_true", help="有违规行时以非零码退出（供池物化前置门禁使用）")
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()

    with args.valuation.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    held = load_codes(args.holdings)
    tiers = {}
    if args.tiers.exists():
        with args.tiers.open(encoding="utf-8-sig") as handle:
            tiers = {r["security_code"]: r.get("quality_tier", "") for r in csv.DictReader(handle)}

    buyable = {"L1": {"低估", "较低估", "中性"}, "L2": {"低估", "较低估"}, "L3": {"低估"}}

    effective = {}
    snapshot = ROOT / "data/interim/pool_effective_tiers.csv"
    if snapshot.exists():
        with snapshot.open(encoding="utf-8-sig") as handle:
            effective = {r["security_code"]: r.get("effective_tier", "") for r in csv.DictReader(handle)}

    failures = []
    for row in rows:
        problems, severity = check_row(row)
        if not problems:
            continue
        code = str(row.get("security_code", "")).strip()
        quality = tiers.get(code, row.get("quality_tier", ""))
        tier_now = effective.get(code) or row.get("valuation_tier", "")
        if code in held:
            priority, reason = 1, "持仓"
        elif tier_now in buyable.get(quality, set()):
            priority, reason = 2, "当前可买"
        else:
            priority, reason = 3, "其余"
        failures.append(
            {
                "priority": priority,
                "priority_reason": reason,
                "severity": severity,
                "security_code": code,
                "security_name": row.get("security_name", ""),
                "quality_tier": quality,
                "strategy_tag": row.get("strategy_tag", ""),
                "valuation_tier": row.get("valuation_tier", ""),
                "fair_price_low": row.get("fair_price_low", ""),
                "fair_price_high": row.get("fair_price_high", ""),
                "band_derivation": row.get("band_derivation", "") or ("fallback" if detect_legacy_fallback(row) else ""),
                "violations": " | ".join(problems),
                "fair_price_basis": row.get("fair_price_basis", ""),
                "queued_at": args.as_of,
            }
        )

    failures.sort(key=lambda r: (0 if r["severity"] == "blocking" else 1, r["priority"], r["security_code"]))
    args.queue_out.parent.mkdir(parents=True, exist_ok=True)
    with args.queue_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(failures[0].keys()) if failures else
                                ["priority", "priority_reason", "severity", "security_code", "security_name",
                                 "quality_tier", "strategy_tag", "valuation_tier", "fair_price_low",
                                 "fair_price_high", "band_derivation", "violations",
                                 "fair_price_basis", "queued_at"])
        writer.writeheader()
        writer.writerows(failures)

    passed = len(rows) - len(failures)
    blocking = [f for f in failures if f["severity"] == "blocking"]
    backfill = [f for f in failures if f["severity"] == "backfill"]

    def by_prio(items):
        counts = {1: 0, 2: 0, 3: 0}
        for item in items:
            counts[item["priority"]] += 1
        return counts

    bcount, fcount = by_prio(blocking), by_prio(backfill)
    print(f"建带校验 {args.as_of}：共 {len(rows)} 行，通过 {passed} 行，未过 {len(failures)} 行")
    print(f"  blocking（带非模型带，降为可持有）{len(blocking)} 行"
          f" —— 持仓 {bcount[1]} / 当前可买 {bcount[2]} / 其余 {bcount[3]}")
    print(f"  backfill（模型带待回填建带卡，限期义务、不阻断买入）{len(backfill)} 行"
          f" —— 持仓 {fcount[1]} / 当前可买 {fcount[2]} / 其余 {fcount[3]}")
    print(f"  重建队列：{args.queue_out}")
    if blocking:
        print("\n  blocking 样例（前 8 行）：")
        for item in blocking[:8]:
            print(f"    [{item['priority_reason']}] {item['security_code']} {item['security_name']}"
                  f" — {item['violations'][:100]}")
        print("\n  处置口径（§6.7 要求 11）：blocking 行降为「可持有」——不得新建仓/加仓，"
              "但不触发 §14 提醒卖出；重建后自动恢复。backfill 行按限期义务补登，买入资格不变。")

    if not args.no_log:
        append_decision_log(
            args.log_file,
            [
                {
                    "logged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "workflow_stage": "valuation_screen",
                    "as_of": args.as_of,
                    "decision_type": "band_validation",
                    "decision_result": "pass" if not failures else "violations_found",
                    "summary_reason": (
                        f"建带校验：{len(rows)} 行中 {passed} 行通过；"
                        f"blocking {len(blocking)} 行（持仓 {bcount[1]}/可买 {bcount[2]}/其余 {bcount[3]}）"
                        f"按 §6.7 要求 11 降为可持有；"
                        f"backfill {len(backfill)} 行（持仓 {fcount[1]}/可买 {fcount[2]}/其余 {fcount[3]}）"
                        f"为建带卡限期回填义务、不阻断买入"
                    ),
                    "input_files": str(args.valuation),
                    "output_file": str(args.queue_out),
                    "operator_or_script": "scripts/validate_valuation_bands.py",
                    "workflow_version": WORKFLOW_VERSION,
                }
            ],
        )

    return 1 if (blocking and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())

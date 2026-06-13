#!/usr/bin/env python3
"""Tier A-share watchlist entries by business quality, excluding current valuation.

The input watchlist is already a final screening output. This script adds a
second-pass quality tier using the personal investment system:

- quality first, valuation later;
- peer-group double checks;
- strict core-candidate anchors;
- low-barrier downgrade pressure.
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "data/processed/a_share_final_watchlist.csv"
FINANCIALS = ROOT / "data/interim/a_share_financial_indicators.csv"
OUTPUT = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
REVIEWED_AT_UTC = "2026-06-13T00:00:00+00:00"

ANCHOR_TIER = {
    # Core anchors from the current core watchlist / explicit reviewer standards.
    "000333": "L1",  # Midea
    "300750": "L1",  # CATL
    "601899": "L1",  # Zijin Mining
    "002371": "L1",  # NAURA
    "688012": "L1",  # AMEC
    "688120": "L1",  # Hwatsing
    "600036": "L1",  # CMB
    # Strong but discounted by cycle, policy, growth, or business-structure risk.
    "002594": "L2",
    "688617": "L2",
    "300760": "L2",
    "600519": "L2",
    "000858": "L2",
    "600809": "L2",
    "603259": "L2",
    "603993": "L2",
    "600111": "L2",
    "000960": "L2",
    "000792": "L2",
    "002466": "L2",
    "002460": "L2",
    "002738": "L2",
    "000408": "L2",
    "002142": "L2",
    "601658": "L2",
    "601128": "L2",
    # Tactical / evidence-building anchors.
    "603605": "L3",
    "000725": "L3",
    "300896": "L3",
    "688008": "L3",
    "688271": "L3",
    "600089": "L3",
}

ANCHOR_EXPLAIN = {
    "L1": "与既有L1锚点（美的集团、宁德时代、紫金矿业、北方华创/中微/华海清科、招商银行）校准：必须具备行业级壁垒、龙头地位或关键瓶颈，并可承受核心候选审查。",
    "L2": "与既有L2锚点（比亚迪、迈瑞医疗、惠泰医疗、贵州茅台、药明康德、五粮液/汾酒、核心资源/银行）校准：壁垒强但存在增长、周期、政策或业务结构折扣。",
    "L3": "与既有L3锚点（京东方、澜起科技、联影医疗、TBEA、珀莱雅、爱美客）校准：有明确关注点，但估值之外仍需等待业务兑现、周期修复或证据增强。",
    "L4": "低优先级观察：仍在原watch池内，但按严格观察池标准，护城河、现金流、行业格局或证据强度不足以与L1-L3锚点并列。",
    "L5": "移出观察池候选：原watch判断需要复核，当前证据更像低壁垒、弱复利、同业可替代或过度依赖周期/主题。",
}

HIGH_COMPOUND = {
    "brand_and_origin_compounding",
    "brand_compounding",
    "scale_and_process_compounding",
    "resource_and_process_compounding",
    "installed_base_and_engineering_compounding",
    "innovation_or_brand_compounding",
    "innovation_compounding",
    "regulated_stable_compounding",
}

MID_COMPOUND = {
    "compound_growth",
    "scale_compounding_if_leader",
    "balance_sheet_compounding",
    "selective_compounding",
    "resource_technology_optionality",
    "brand_location_compounding_if_leader",
}

LOW_COMPOUND = {
    "low_compounding",
    "limited_compounding",
    "weak_or_selective_compounding",
    "unproven_compounding",
}

WEIGHTS = {
    "business_moat_score": 0.20,
    "technology_barrier_score": 0.18,
    "market_position_score": 0.18,
    "business_quality_score": 0.14,
    "operating_quality_score": 0.12,
    "industry_outlook_score": 0.12,
    "governance_risk_score": 0.06,
}

LOW_BARRIER_TERMS = [
    "超市",
    "普通零售",
    "服装",
    "纺织",
    "贸易",
    "营销服务",
    "包装印刷",
    "塑料制品",
    "其他化学制品",
    "其他通用机械",
    "食品综合",
    "日用化学",
    "宠物",
    "景区",
    "酒店",
    "陶瓷",
    "玻璃",
    "水泥",
    "普钢",
    "涤纶",
    "橡胶制品",
]

L1_HARD_BARRIER_TERMS = [
    "半导体",
    "集成电路",
    "半导体设备",
    "基础软件",
    "行业应用软件",
    "光学元件",
    "通信传输",
    "通信终端",
    "动力电池",
    "储能",
    "输变电",
    "电气自控",
    "电气仪表",
    "医疗器械",
    "CXO",
    "生物医药",
    "航空",
    "航天",
    "军工",
    "机器人",
    "仪器仪表",
    "专用计算机",
    "服务器",
    "电子元件",
]

L1_REGULATED_TERMS = ["银行", "水电", "铁路运输", "通信运营"]


def flt(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
        return None if math.isnan(number) else number
    except (TypeError, ValueError):
        return None


def text_has(text: str | None, terms: list[str]) -> bool:
    text = text or ""
    return any(term in text for term in terms)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def classify_strategy(row: dict[str, str]) -> str:
    peer_group = row["peer_groups"] or ""
    cyclicality = row["cyclicality_profile"] or ""
    compounding = row["compounding_profile"] or ""

    # Order matters: "金融" must not be matched as a gold/resource term.
    if (
        text_has(peer_group, ["银行", "证券", "保险", "水务", "燃气", "电力", "高速", "港口", "铁路", "机场", "公用事业"])
        or "regulated_stable" in compounding
        or "balance_sheet" in compounding
    ):
        return "G-股东回报型低估/稳健资产"

    if (
        "strategic_resource" in cyclicality
        or "resource_and_process" in compounding
        or text_has(peer_group, ["有色金属", "煤炭", "稀土", "锂", "铜", "黄金", "钨", "锡", "铝", "矿", "资源", "盐湖", "钾肥", "油气", "石油"])
    ):
        return "F-垄断资源型"

    if (
        text_has(peer_group, ["半导体", "集成电路", "光学", "光电子", "通信", "计算机", "软件", "机器人", "航空", "航天", "军工", "输变电", "储能", "动力电池", "新能源", "电子设备", "电子元件", "医疗器械", "CXO", "生物医药", "创新药", "专用设备", "高端"])
        or "innovation" in compounding
        or "grid_capex" in cyclicality
    ):
        if text_has(peer_group, ["半导体", "集成电路", "光学", "通信", "机器人", "动力电池", "储能", "输变电", "航空", "航天", "电子设备", "电子元件"]):
            return "D-产业链爆发/关键瓶颈型"
        return "C-GARP成长型"

    if text_has(peer_group, ["白酒", "饮料", "食品", "家电", "日用化学", "医药商业", "中药"]) or "brand" in compounding:
        return "A-DCF/现金流复利型"

    if text_has(peer_group, ["房地产", "旅游", "酒店", "免税", "传媒", "教育", "互联网"]) or "deep_cyclical_or_structural_headwind" in cyclicality:
        return "E-落难白马/反转型"

    if "commodity_cycle" in cyclicality or text_has(peer_group, ["化工", "钢铁", "建材", "玻璃", "造纸", "纺织", "橡胶", "塑料"]):
        return "F-周期资源/材料型"

    return "C-GARP成长型"


def raw_score(row: dict[str, str]) -> tuple[float, list[str]]:
    score = 0.0
    missing: list[str] = []
    for column, weight in WEIGHTS.items():
        value = flt(row.get(column))
        if value is None:
            value = 50.0
            missing.append(column)
        score += value * weight
    return score, missing


def compounding_adjustment(label: str) -> float:
    if label in HIGH_COMPOUND:
        return 5.0
    if label in MID_COMPOUND:
        return 1.0
    if label in LOW_COMPOUND:
        return -6.0
    return -1.0


def cyclicality_adjustment(label: str) -> float:
    if label in ["low_cyclicality", "low_to_moderate_cyclicality", "defensive_growth_with_policy_risk", "grid_capex_structural_growth"]:
        return 2.0
    if label in ["structural_growth_with_manufacturing_cycle", "cyclical_structural_growth", "strategic_resource_cycle", "strategic_critical_material_cycle"]:
        return 1.0
    if label in ["commodity_cycle", "capex_cycle", "unclear_cycle_with_possible_innovation_tailwind", "unclear_cycle"]:
        return -2.0
    if label in ["high_competition_growth_cycle", "consumer_cycle_competitive"]:
        return -4.0
    if label == "deep_cyclical_or_structural_headwind":
        return -7.0
    return 0.0


def route_adjustment(route: str) -> float:
    if route == "direct_watch":
        return 3.0
    if "direct_watch" in route:
        return 2.0
    return 0.0


def financial_adjustment(row: dict[str, str], financial: dict[str, str], strategy: str) -> tuple[float, str]:
    adjustment = 0.0
    notes: list[str] = []
    peer_group = row["peer_groups"]
    is_financial = strategy.startswith("G-") and text_has(peer_group, ["银行", "证券", "保险"])

    gross_margin = flt(financial.get("gross_margin_pct"))
    net_margin = flt(financial.get("net_margin_pct"))
    roe = flt(financial.get("roe_weighted_pct"))
    roic = flt(financial.get("roic_pct"))
    cashflow_to_revenue = flt(financial.get("cashflow_to_revenue_pct"))
    debt_asset_ratio = flt(financial.get("debt_asset_ratio_pct"))
    revenue_yoy = flt(financial.get("revenue_yoy_pct"))
    profit_yoy = flt(financial.get("profit_yoy_pct"))
    rd_to_revenue = flt(financial.get("research_expense_to_revenue_pct"))

    if gross_margin is not None and gross_margin >= 45:
        adjustment += 1.5
        notes.append("毛利率高")
    if net_margin is not None:
        if net_margin >= 20:
            adjustment += 2.0
            notes.append("净利率高")
        elif net_margin < 0:
            adjustment -= 4.0
            notes.append("净利率为负")
        elif net_margin < 5 and not strategy.startswith("F-"):
            adjustment -= 1.5
            notes.append("净利率薄")
    if roe is not None:
        if roe >= 18:
            adjustment += 2.0
            notes.append("ROE高")
        elif roe < 5 and not is_financial:
            adjustment -= 2.0
            notes.append("ROE弱")
    if roic is not None:
        if roic >= 12:
            adjustment += 1.5
            notes.append("ROIC较好")
        elif roic < 3 and not is_financial:
            adjustment -= 1.0
            notes.append("ROIC偏弱")
    if cashflow_to_revenue is not None:
        if cashflow_to_revenue >= 10:
            adjustment += 1.5
            notes.append("现金流转化好")
        elif cashflow_to_revenue < 0:
            adjustment -= 2.0
            notes.append("经营现金流承压")
    if (
        debt_asset_ratio is not None
        and debt_asset_ratio >= 70
        and not is_financial
        and not text_has(peer_group, ["银行", "证券", "保险", "电力", "公用事业"])
    ):
        adjustment -= 1.5
        notes.append("资产负债率高")
    if revenue_yoy is not None and revenue_yoy < -10:
        adjustment -= 1.0
        notes.append("收入下滑")
    if profit_yoy is not None and profit_yoy < -20:
        adjustment -= 1.5
        notes.append("利润下滑")
    if rd_to_revenue is not None and rd_to_revenue >= 8 and (strategy.startswith("C-") or strategy.startswith("D-")):
        adjustment += 1.5
        notes.append("研发强度高")

    return adjustment, "；".join(notes) if notes else "未见足以改变分档的财务异常或加分项"


def tier_label(tier: str) -> str:
    return {
        "L1": "L1-核心候选",
        "L2": "L2-准核心候选",
        "L3": "L3-战术/重点观察",
        "L4": "L4-低优先级观察",
        "L5": "L5-移出观察池候选",
    }[tier]


def pe_peg_note(strategy: str) -> str:
    if strategy.startswith("C-"):
        return "本轮不按当前PE/PEG分档；下一轮需用行业空间、份额、利润率路径重建未来增速和PEG。"
    if strategy.startswith("D-"):
        return "本轮不按当前PE分档；产业链爆发需用2-3年正常化利润、订单/产能/客户验证重估PEG。"
    if strategy.startswith("F-"):
        return "本轮不按当前PE分档；周期/资源股需使用中枢商品价格和穿越周期现金流。"
    if strategy.startswith("A-"):
        return "本轮不按当前估值分档；后续用自由现金流收益率、增长、分红回购评估预期收益。"
    if strategy.startswith("B-") or strategy.startswith("G-"):
        return "本轮不按当前低估幅度分档；后续需用PB/清算价值/现金和股东回报验证安全边际。"
    return "本轮不考虑当前估值水平；PE/PB/PEG留待单独Valuation Assessment。"


def tier_reasons(tier: str) -> tuple[str, str]:
    if tier == "L1":
        return (
            "具备核心候选资格：行业/同业排名靠前，壁垒、市场地位或关键瓶颈足以对标既有L1锚点。",
            "已为最高业务质量档；下一步只需单独做估值和右侧触发，不因本轮分档给出买入结论。",
        )
    if tier == "L2":
        return (
            "具备准核心资格：护城河、技术壁垒、资源/品牌/平台能力或经营质量明确，但与L1锚点相比仍有周期、成长、政策或业务结构折扣。",
            "未上L1：与L1锚点相比，行业空间、利润稳定性、同业统治力或现金流穿越周期能力仍弱一档。",
        )
    if tier == "L3":
        return (
            "适合战术或重点观察：存在产业链、周期修复、技术替代、品牌/渠道或资源期权，但证据强度或商业质量不足以支持准核心。",
            "未上L2：相对L2锚点，护城河、利润率、现金流质量、市场地位或新玩家进入难度仍需更多证据。",
        )
    if tier == "L4":
        return (
            "低优先级观察：仍保留研究价值，但业务壁垒、现金流、同业地位或复利属性偏弱，不能占用重点观察名额。",
            "未上L3：缺少明确差异化优势，或行业/产品容易被资本、渠道、产能或同业复制。",
        )
    return (
        "移出观察池候选：按当前严格标准，更像低壁垒、弱复利、同业可替代或主题/周期暴露，需重新证明长期关注价值。",
        "未上L4：原watch理由不足以支撑持续观察，除非后续权威披露显示不可替代优势或明确催化。",
    )


def assign_tier(row: dict[str, str]) -> tuple[str, str]:
    code = row["security_code"]
    if code in ANCHOR_TIER:
        return ANCHOR_TIER[code], "yes"

    score = row["_adjusted_quality_score"]
    compounding = row["compounding_profile"]
    cyclicality = row["cyclicality_profile"]
    peer_group = row["peer_groups"]
    direct = "direct_watch" in row["watch_selection_route"]
    peer_percentile = row["_peer_percentile"]
    moat = flt(row.get("business_moat_score")) or 0
    tech = flt(row.get("technology_barrier_score")) or 0
    market = flt(row.get("market_position_score")) or 0
    low_barrier = text_has(peer_group, LOW_BARRIER_TERMS)
    hard_barrier = text_has(peer_group, L1_HARD_BARRIER_TERMS)
    regulated_l1 = text_has(peer_group, L1_REGULATED_TERMS)

    can_l2_hard = (
        direct
        and score >= 88
        and peer_percentile <= 0.10
        and hard_barrier
        and tech >= 75
        and market >= 80
        and moat >= 62
        and compounding not in LOW_COMPOUND
        and not low_barrier
    )
    can_l2_regulated = (
        direct
        and score >= 88
        and peer_percentile <= 0.10
        and regulated_l1
        and market >= 85
        and moat >= 70
        and compounding in HIGH_COMPOUND
    )

    # L1 is intentionally anchor-only. New names can be promoted after a
    # dedicated deep review; a batch pass should not manufacture core anchors.
    if can_l2_hard or can_l2_regulated:
        tier = "L2"
    elif score >= 74 and peer_percentile <= 0.35 and compounding not in {"low_compounding", "limited_compounding"} and cyclicality != "deep_cyclical_or_structural_headwind":
        tier = "L2"
    elif score >= 63 and peer_percentile <= 0.70 and compounding != "low_compounding":
        tier = "L3"
    elif score >= 53:
        tier = "L4"
    else:
        tier = "L5"

    if tier == "L2" and peer_percentile > 0.55 and not direct:
        tier = "L3"
    if tier == "L3" and peer_percentile > 0.85 and compounding in LOW_COMPOUND:
        tier = "L4"
    if tier in {"L1", "L2"} and (moat < 55 or market < 55):
        tier = "L3"
    if tier == "L1" and low_barrier:
        tier = "L2"

    return tier, "no"


def main() -> None:
    financials = {row["security_code"]: row for row in load_csv(FINANCIALS)}
    rows = load_csv(WATCHLIST)

    for row in rows:
        strategy = classify_strategy(row)
        base_score, missing = raw_score(row)
        finance_adjustment, finance_note = financial_adjustment(row, financials.get(row["security_code"], {}), strategy)
        adjusted = (
            base_score
            + compounding_adjustment(row["compounding_profile"])
            + cyclicality_adjustment(row["cyclicality_profile"])
            + route_adjustment(row["watch_selection_route"])
            + finance_adjustment
        )
        if row["compounding_profile"] in LOW_COMPOUND and (flt(row.get("business_moat_score")) or 0) < 65:
            adjusted -= 4
        if text_has(row["peer_groups"], LOW_BARRIER_TERMS) and row["watch_selection_route"] != "direct_watch":
            adjusted -= 2

        row["_strategy"] = strategy
        row["_base_quality_score"] = base_score
        row["_adjusted_quality_score"] = max(0.0, min(100.0, adjusted))
        row["_financial_note"] = finance_note
        row["_missing_score_fields"] = ";".join(missing)

    peer_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        peer_groups[row["peer_groups"]].append(row)

    for items in peer_groups.values():
        ordered = sorted(items, key=lambda item: item["_adjusted_quality_score"], reverse=True)
        peer_count = len(ordered)
        for rank, row in enumerate(ordered, start=1):
            row["_peer_rank"] = rank
            row["_peer_count"] = peer_count
            row["_peer_percentile"] = rank / peer_count
            row["_peer_top_name"] = ordered[0]["security_name"]
            row["_peer_top_code"] = ordered[0]["security_code"]

    for row in rows:
        tier, anchor_override = assign_tier(row)
        qualification, not_upper = tier_reasons(tier)
        moat = flt(row.get("business_moat_score")) or 0
        tech = flt(row.get("technology_barrier_score")) or 0
        market = flt(row.get("market_position_score")) or 0
        business_quality = flt(row.get("business_quality_score")) or 0
        operating_quality = flt(row.get("operating_quality_score")) or 0
        industry_outlook = flt(row.get("industry_outlook_score")) or 0

        row["_tier"] = tier
        row["_tier_label"] = tier_label(tier)
        row["_qualification_reason"] = qualification
        row["_not_upper_tier_reason"] = not_upper
        row["_peer_check"] = (
            f"同行组 {row['peer_groups']} 内质量排名 {row['_peer_rank']}/{row['_peer_count']}；"
            f"组内最高为 {row['_peer_top_name']}({row['_peer_top_code']})。{ANCHOR_EXPLAIN[tier]}"
        )
        row["_moat_summary"] = (
            f"护城河{moat:.2f}/技术{tech:.2f}/市场地位{market:.2f}；"
            f"{row['capability_assessment'] or row['decision_reason']}"
        )
        row["_operating_summary"] = (
            f"商业质量{business_quality:.2f}/经营质量{operating_quality:.2f}/行业前景{industry_outlook:.2f}；"
            f"财务辅助判断：{row['_financial_note']}。"
        )
        row["_pe_peg_note"] = pe_peg_note(row["_strategy"])
        row["_anchor_override"] = anchor_override

    fields = [
        "market_type",
        "market_label",
        "security_code",
        "security_name",
        "listed_company_name",
        "exchange",
        "industry",
        "peer_groups",
        "quality_tier",
        "quality_tier_label",
        "primary_strategy_tag",
        "adjusted_quality_score",
        "base_dimension_score",
        "peer_rank",
        "peer_count",
        "peer_percentile",
        "watch_selection_route",
        "prior_preliminary_attention",
        "triage_score",
        "triage_decision",
        "business_moat_score",
        "technology_barrier_score",
        "market_position_score",
        "business_quality_score",
        "operating_quality_score",
        "industry_outlook_score",
        "governance_risk_score",
        "cyclicality_profile",
        "compounding_profile",
        "moat_and_barrier_summary",
        "operating_financial_summary",
        "pe_peg_role_note",
        "peer_double_check",
        "tier_qualification_reason",
        "not_upper_tier_reason",
        "decision_reason",
        "calibrated_standard_implication",
        "financial_report_date",
        "gross_margin_pct",
        "net_margin_pct",
        "roe_weighted_pct",
        "roic_pct",
        "cashflow_to_revenue_pct",
        "debt_asset_ratio_pct",
        "revenue_yoy_pct",
        "profit_yoy_pct",
        "research_expense_to_revenue_pct",
        "source_decision_files",
        "source_urls",
        "evidence_basis",
        "authority_refresh_needed",
        "analysis_batch_id",
        "reviewed_at_utc",
    ]

    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            financial = financials.get(row["security_code"], {})
            source_urls = (row.get("source_urls") or "")
            if financial.get("source_urls"):
                source_urls = f"{source_urls};{financial['source_urls']}" if source_urls else financial["source_urls"]
            authority_refresh_needed = "yes" if "eastmoney" in source_urls.lower() else "no"
            writer.writerow(
                {
                    "market_type": row["market_type"],
                    "market_label": row["market_label"],
                    "security_code": row["security_code"],
                    "security_name": row["security_name"],
                    "listed_company_name": row["listed_company_name"],
                    "exchange": row["exchange"],
                    "industry": row["industry"],
                    "peer_groups": row["peer_groups"],
                    "quality_tier": row["_tier"],
                    "quality_tier_label": row["_tier_label"],
                    "primary_strategy_tag": row["_strategy"],
                    "adjusted_quality_score": f"{row['_adjusted_quality_score']:.2f}",
                    "base_dimension_score": f"{row['_base_quality_score']:.2f}",
                    "peer_rank": row["_peer_rank"],
                    "peer_count": row["_peer_count"],
                    "peer_percentile": f"{row['_peer_percentile']:.4f}",
                    "watch_selection_route": row["watch_selection_route"],
                    "prior_preliminary_attention": row["prior_preliminary_attention"],
                    "triage_score": row["triage_score"],
                    "triage_decision": row["triage_decision"],
                    "business_moat_score": row["business_moat_score"],
                    "technology_barrier_score": row["technology_barrier_score"],
                    "market_position_score": row["market_position_score"],
                    "business_quality_score": row["business_quality_score"],
                    "operating_quality_score": row["operating_quality_score"],
                    "industry_outlook_score": row["industry_outlook_score"],
                    "governance_risk_score": row["governance_risk_score"],
                    "cyclicality_profile": row["cyclicality_profile"],
                    "compounding_profile": row["compounding_profile"],
                    "moat_and_barrier_summary": row["_moat_summary"],
                    "operating_financial_summary": row["_operating_summary"],
                    "pe_peg_role_note": row["_pe_peg_note"],
                    "peer_double_check": row["_peer_check"],
                    "tier_qualification_reason": row["_qualification_reason"],
                    "not_upper_tier_reason": row["_not_upper_tier_reason"],
                    "decision_reason": row["decision_reason"],
                    "calibrated_standard_implication": row["calibrated_standard_implication"],
                    "financial_report_date": financial.get("latest_report_date", ""),
                    "gross_margin_pct": financial.get("gross_margin_pct", ""),
                    "net_margin_pct": financial.get("net_margin_pct", ""),
                    "roe_weighted_pct": financial.get("roe_weighted_pct", ""),
                    "roic_pct": financial.get("roic_pct", ""),
                    "cashflow_to_revenue_pct": financial.get("cashflow_to_revenue_pct", ""),
                    "debt_asset_ratio_pct": financial.get("debt_asset_ratio_pct", ""),
                    "revenue_yoy_pct": financial.get("revenue_yoy_pct", ""),
                    "profit_yoy_pct": financial.get("profit_yoy_pct", ""),
                    "research_expense_to_revenue_pct": financial.get("research_expense_to_revenue_pct", ""),
                    "source_decision_files": row["source_decision_files"],
                    "source_urls": source_urls,
                    "evidence_basis": "existing_final_screening_result + peer_group_calibration + local_financial_indicators; current_market_valuation_excluded_by_request",
                    "authority_refresh_needed": authority_refresh_needed,
                    "analysis_batch_id": f"batch-{(index - 1) // 100 + 1:02d}",
                    "reviewed_at_utc": REVIEWED_AT_UTC,
                }
            )

    print(OUTPUT.relative_to(ROOT))
    print("rows", len(rows))
    print("tiers", Counter(row["_tier"] for row in rows))
    print("strategies", Counter(row["_strategy"] for row in rows).most_common())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create dimensional Hong Kong moat scores from fetched research evidence."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


DEFAULT_RAW = Path("data/raw/hong_kong_securities.csv")
DEFAULT_PROFILES = Path("data/interim/hong_kong_company_profiles.csv")
DEFAULT_FINANCIALS = Path("data/interim/hong_kong_financial_indicators.csv")
DEFAULT_OUTPUT = Path("data/processed/hong_kong_full_coverage_scores.csv")
DEFAULT_WATCHLIST = Path("data/processed/hong_kong_full_coverage_watchlist.csv")
SCORING_MODEL_VERSION = "full_coverage_dimensional_v0.4"

DIMENSIONS = [
    ("business_moat", 0.28),
    ("technology_barrier", 0.24),
    ("market_position", 0.14),
    ("business_quality", 0.08),
    ("operating_quality", 0.06),
    ("industry_outlook", 0.14),
    ("governance_risk", 0.06),
]
DIMENSION_WEIGHT_POINTS = {
    "business_moat": 28,
    "technology_barrier": 24,
    "market_position": 14,
    "business_quality": 8,
    "operating_quality": 6,
    "industry_outlook": 14,
    "governance_risk": 6,
}

OUTPUT_COLUMNS = [
    "market_type",
    "market_label",
    "security_code",
    "symbol",
    "exchange",
    "board",
    "listed_company_name",
    "security_name",
    "currency",
    "isin",
    "listing_date",
    "industry",
    "eligibility_status",
    "screening_status",
    "disclosure_status",
    "peer_group",
    "peer_relative_position",
    "cyclicality_profile",
    "compounding_profile",
    "business_moat_score",
    "business_moat_level",
    "business_moat_reason",
    "technology_barrier_score",
    "technology_barrier_level",
    "technology_barrier_reason",
    "market_position_score",
    "market_position_level",
    "market_position_reason",
    "business_quality_score",
    "business_quality_level",
    "business_quality_reason",
    "operating_quality_score",
    "operating_quality_level",
    "operating_quality_reason",
    "industry_outlook_score",
    "industry_outlook_level",
    "industry_outlook_reason",
    "governance_risk_score",
    "governance_risk_level",
    "governance_risk_reason",
    "weighted_total_score",
    "overall_level",
    "overall_reason",
    "evidence_confidence",
    "source_urls",
    "reviewed_at_utc",
    "scoring_model_version",
]

WATCHLIST_COLUMNS = [
    "security_code",
    "security_name",
    "score_total",
    "score_business_moat",
    "score_technology_barrier",
    "score_market_position",
    "score_business_quality",
    "score_operating_quality",
    "score_industry_outlook",
    "score_governance_risk",
    "peer_group",
    "peer_relative_position",
    "scoring_model_version",
]

WATCHLIST_SCORE_FIELDS = [
    ("score_total", "总分", "weighted_total_score"),
    ("score_business_moat", "护城河", "business_moat_score"),
    ("score_technology_barrier", "技术壁垒", "technology_barrier_score"),
    ("score_market_position", "市场地位", "market_position_score"),
    ("score_business_quality", "商业质量", "business_quality_score"),
    ("score_operating_quality", "经营质量", "operating_quality_score"),
    ("score_industry_outlook", "行业前景", "industry_outlook_score"),
    ("score_governance_risk", "治理风险", "governance_risk_score"),
]


class ScoringError(RuntimeError):
    """Raised when Hong Kong full-coverage scoring inputs are invalid."""


@dataclass(frozen=True)
class IndustryPrior:
    business_moat: int
    technology_barrier: int
    business_quality: int
    capital_replicability: str


@dataclass(frozen=True)
class IndustryOutlook:
    score: float
    cyclicality_profile: str
    compounding_profile: str
    reason: str


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise ScoringError(f"CSV not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        if not reader.fieldnames:
            raise ScoringError(f"CSV has no header: {path}")
        return list(reader.fieldnames), rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def by_code(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    _, rows = read_csv(path)
    return {row["security_code"]: row for row in rows if row.get("security_code")}


def f(value: str | None) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def clamp(value: float, low: int = 0, high: int = 100) -> float:
    return round(max(low, min(high, float(value))), 2)


def weighted_score(scores: dict[str, float]) -> float:
    numerator = sum(scores[name] * DIMENSION_WEIGHT_POINTS[name] for name in DIMENSION_WEIGHT_POINTS)
    return clamp(numerator / 100)


def fmt_score(score: float) -> str:
    return f"{score:.2f}"


def level(score: float) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "E"


def parse_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def percentile_maps(rows: list[dict[str, str]], peer_key: str, metric: str, reverse: bool = False) -> dict[str, float]:
    by_peer: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        value = f(row.get(metric))
        if value is None:
            continue
        by_peer.setdefault(row[peer_key], []).append((row["security_code"], value))
    result: dict[str, float] = {}
    for items in by_peer.values():
        values = sorted(value for _, value in items)
        if len(values) == 1:
            for code, _ in items:
                result[code] = 50.0
            continue
        for code, value in items:
            rank = values.index(value)
            pct = 100 * (1 - rank / (len(values) - 1)) if reverse else 100 * rank / (len(values) - 1)
            result[code] = pct
    return result


def keyword_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def resource_leader_signal(industry_text: str, profile_text: str) -> bool:
    lower_profile = profile_text.lower()
    if not (
        keyword_any(industry_text, ["矿", "黄金", "铜", "有色", "金属", "煤", "石油", "天然气"])
        or keyword_any(industry_text.lower(), ["mining", "gold", "copper", "metal", "resource", "oil", "gas"])
    ):
        return False
    signals = [
        keyword_any(profile_text, ["全球", "跨国矿业", "全球领先", "世界", "重要矿业基地"]) or keyword_any(lower_profile, ["global", "world", "international mining"]),
        keyword_any(profile_text, ["自主勘查", "逆周期并购", "资源获取成本", "资源优先", "资源量", "储量", "重要成矿带"]) or keyword_any(lower_profile, ["exploration", "reserves", "resources", "acquisition"]),
        keyword_any(profile_text, ["矿石流五环归一", "低品位", "难处理", "矿业工程", "采矿", "选矿", "冶炼"]) or keyword_any(lower_profile, ["low-grade", "mining engineering", "mining", "processing", "smelting"]),
        keyword_any(profile_text, ["全球前", "位居前", "全球排名", "龙头", "前3位", "前4位"]) or keyword_any(lower_profile, ["leading", "largest", "top"]),
    ]
    return sum(signals) >= 3


def strategic_critical_material_signal(industry_text: str, profile_text: str) -> bool:
    text = f"{industry_text} {profile_text}"
    if not keyword_any(text, ["锗", "镓", "铟", "钨", "钼", "锑", "钽", "稀散", "稀有小金属", "化合物半导体", "砷化镓", "磷化铟", "germanium", "gallium", "indium", "tungsten", "molybdenum", "critical mineral", "compound semiconductor"]):
        return False
    signals = [
        keyword_any(text, ["矿", "资源", "储量", "采矿权", "探矿权", "自有矿山", "完整产业链", "mine", "mining", "reserve", "resource"]),
        keyword_any(text, ["精深加工", "高纯", "晶片", "单晶", "红外", "光纤", "空间", "半导体材料", "purification", "wafer", "crystal", "infrared", "optical", "semiconductor material"]),
        keyword_any(text, ["国家级企业技术中心", "工程技术研究中心", "行业标准", "国家标准", "单项冠军", "专精特新", "standard", "champion", "specialized"]),
        keyword_any(text, ["出口管制", "战略资源", "关键材料", "卡脖子", "国产替代", "export control", "strategic resource", "supply security"]),
    ]
    return sum(signals) >= 2


def grid_core_equipment_signal(industry_text: str, profile_text: str) -> bool:
    text = f"{industry_text} {profile_text}"
    if not keyword_any(text, ["输变电", "变压器", "电抗器", "互感器", "特高压", "超高压", "换流阀", "直流输电", "电网", "power transmission", "transformer", "reactor", "uhv", "ultra-high voltage", "high voltage direct current", "grid equipment"]):
        return False
    signals = [
        keyword_any(text, ["特高压", "超高压", "交直流", "高压直流", "换流阀", "首台套", "uhv", "ultra-high voltage", "hvdc", "converter valve"]),
        keyword_any(text, ["国家电网", "南方电网", "国家重大项目", "示范工程", "一体化集成", "境外机电行业输变电", "电力工程施工总承包特级资质", "state grid", "grid project", "integrated solution"]),
        keyword_any(text, ["全球领先", "全球市场份额领先", "全球高端输变电", "世界领先", "国际领先", "行业领先", "行业前列", "产能稳居", "中国电气工业100强第1位", "大型能源装备", "global leader", "world leading", "international leader", "leading market share"]),
        keyword_any(text, ["国家级", "企业技术中心", "高新技术企业", "专精特新", "进口替代", "创新100强", "national", "technology center", "import substitution"]),
    ]
    return sum(signals) >= 2


def industry_prior(peer_group: str, profile_text: str) -> IndustryPrior:
    text = f"{peer_group} {profile_text}"
    lower_text = text.lower()
    industry_text = peer_group
    lower_industry = industry_text.lower()
    if strategic_critical_material_signal(industry_text, profile_text):
        return IndustryPrior(74, 82, 58, "strategic scarce materials combine resource access, purification, crystal or compound processing, standards, and customer qualification that capital alone cannot compress quickly")
    if grid_core_equipment_signal(industry_text, profile_text):
        return IndustryPrior(72, 78, 62, "ultra-high-voltage grid equipment requires long engineering accumulation, safety validation, grid qualification, and project references that capital alone cannot buy quickly")
    if keyword_any(industry_text, ["银行", "保险", "金融", "证券", "信托", "资产管理"]) or keyword_any(lower_industry, ["bank", "insurance", "financial", "securities", "asset management"]):
        return IndustryPrior(72, 45, 64, "licenses regulation customer relationships and risk systems reduce pure capital replicability")
    if keyword_any(industry_text, ["公用", "电力", "燃气", "水务", "电讯", "电信", "港口", "机场", "高速", "铁路"]) or keyword_any(lower_industry, ["utilities", "power", "gas", "water", "telecommunication", "port", "airport", "railway"]):
        return IndustryPrior(78, 42, 72, "regulated infrastructure assets concessions and network coverage are difficult to buy quickly")
    if keyword_any(industry_text, ["软件", "资讯科技", "互联网", "媒体", "游戏", "电子商贸"]) or keyword_any(lower_industry, ["software", "internet", "media", "games", "e-commerce"]):
        return IndustryPrior(66, 72, 62, "platform data user network and product capability require more than capital")
    if keyword_any(industry_text, ["药", "医疗", "生物", "保健"]) or keyword_any(lower_industry, ["pharmaceutical", "biotech", "health care", "healthcare", "medical"]):
        return IndustryPrior(65, 76, 62, "clinical validation regulation distribution and trust limit pure capital entry")
    if keyword_any(industry_text, ["半导体", "芯片", "电子", "硬件"]) or keyword_any(lower_industry, ["semiconductor", "chip", "electronics", "hardware"]):
        return IndustryPrior(62, 78, 58, "process know how supply chain qualification and customer validation take time")
    if keyword_any(industry_text, ["汽车", "电池", "新能源", "光伏", "能源设备"]) or keyword_any(lower_industry, ["automobile", "battery", "new energy", "solar", "energy equipment"]):
        return IndustryPrior(58, 70, 54, "manufacturing scale helps but process yield supply chain and customers are not instantly bought")
    if keyword_any(industry_text, ["食品", "饮料", "酒", "服饰", "体育用品", "化妆", "消费品"]) or keyword_any(lower_industry, ["food", "beverage", "apparel", "sportswear", "cosmetic", "consumer"]):
        return IndustryPrior(74, 45, 70, "consumer brand channel and product trust are costly to replicate quickly")
    if keyword_any(industry_text, ["地产", "物业", "建筑", "建材"]) or keyword_any(lower_industry, ["properties", "property", "construction", "building materials"]):
        return IndustryPrior(42, 38, 38, "land project access leverage and execution are cyclical and comparatively replicable")
    if keyword_any(industry_text, ["零售", "百货", "超市", "贸易", "批发"]) or keyword_any(lower_industry, ["retail", "department store", "supermarket", "trading", "wholesale"]):
        return IndustryPrior(42, 35, 45, "store formats logistics and distribution can often be replicated with capital")
    if keyword_any(industry_text, ["博彩", "旅游", "酒店", "餐饮", "教育"]) or keyword_any(lower_industry, ["gaming", "tourism", "hotel", "restaurant", "leisure", "education"]):
        return IndustryPrior(58, 42, 52, "brand location licenses and operations matter but demand can be cyclical")
    if resource_leader_signal(industry_text, profile_text):
        return IndustryPrior(66, 68, 56, "scarce resource base global mine portfolio exploration M&A integration and mining-engineering know-how reduce pure capital replicability despite commodity exposure")
    if keyword_any(industry_text, ["矿", "石油", "煤", "钢", "金属", "材料", "化工"]) or keyword_any(lower_industry, ["mining", "oil", "coal", "steel", "metal", "materials", "chemical"]):
        return IndustryPrior(52, 58, 50, "resource cost process scale and cycles matter but commodity exposure lowers durability")
    if keyword_any(text, ["研发", "专利", "平台", "算法", "科技", "创新"]) or keyword_any(lower_text, ["research", "r&d", "patent", "platform", "algorithm", "technology", "innovation"]):
        return IndustryPrior(52, 62, 52, "profile suggests technical or product capability but industry classification is broad")
    return IndustryPrior(50, 50, 50, "industry evidence does not show a clearly hard-to-replicate structure")


def industry_outlook(peer_group: str, profile_text: str) -> IndustryOutlook:
    industry_text = peer_group
    lower_industry = industry_text.lower()
    if strategic_critical_material_signal(industry_text, profile_text):
        return IndustryOutlook(72, "strategic_critical_material_cycle", "resource_technology_optionality", "Strategic scarce materials can benefit from semiconductors, aerospace, AI infrastructure, optical communication, and supply-security demand; price cycles and capacity ramp risks still keep the score below elite compounders.")
    if grid_core_equipment_signal(industry_text, profile_text):
        return IndustryOutlook(68, "grid_capex_structural_growth", "installed_base_and_engineering_compounding", "Grid modernization, UHV transmission, renewable power integration, and overseas power-infrastructure demand support long-cycle growth, though customer capex cycles and project timing remain material.")
    if keyword_any(industry_text, ["软件", "资讯科技", "互联网", "媒体", "游戏", "电子商贸", "云", "人工智能", "数据"]) or keyword_any(lower_industry, ["software", "internet", "media", "games", "e-commerce", "cloud", "data", "artificial intelligence"]):
        return IndustryOutlook(78, "low_to_moderate_cyclicality", "compound_growth", "Digitalization, data, AI, platform, and online-service demand support multi-year growth, with leader quality depending on retention and network effects.")
    if keyword_any(industry_text, ["汽车", "电池", "新能源", "光伏", "能源设备"]) or keyword_any(lower_industry, ["automobile", "battery", "new energy", "solar", "energy equipment", "ev"]):
        return IndustryOutlook(66, "structural_growth_with_manufacturing_cycle", "scale_compounding_if_leader", "Electrification and storage are structural growth markets, but Hong Kong-listed manufacturers can still face price, capacity, and policy cycles.")
    if keyword_any(industry_text, ["半导体", "芯片", "电子", "硬件", "机器人", "自动化"]) or keyword_any(lower_industry, ["semiconductor", "chip", "electronics", "hardware", "robotics", "automation"]):
        return IndustryOutlook(72, "cyclical_structural_growth", "innovation_compounding", "AI, localization, and automation support demand, while semiconductor and hardware cycles keep outcomes uneven.")
    if keyword_any(industry_text, ["药", "医疗", "生物", "保健"]) or keyword_any(lower_industry, ["pharmaceutical", "biotech", "health care", "healthcare", "medical"]):
        return IndustryOutlook(70, "defensive_growth_with_policy_risk", "innovation_or_brand_compounding", "Aging, healthcare demand, and innovation support long-term growth, but procurement, pricing, and clinical risks reduce certainty.")
    if keyword_any(industry_text, ["食品", "饮料", "酒", "服饰", "体育用品", "化妆", "消费品"]) or keyword_any(lower_industry, ["food", "beverage", "apparel", "sportswear", "cosmetic", "consumer", "tobacco"]):
        return IndustryOutlook(70, "low_to_moderate_cyclicality", "brand_compounding", "Brand, habit, and channel advantages can compound, though discretionary categories such as apparel are more cyclical than staples.")
    if keyword_any(industry_text, ["公用", "电力", "燃气", "水务", "电讯", "电信", "港口", "机场", "高速", "铁路"]) or keyword_any(lower_industry, ["utilities", "power", "gas", "water", "telecommunication", "port", "airport", "railway"]):
        return IndustryOutlook(62, "low_cyclicality", "regulated_stable_compounding", "Regulated networks and infrastructure assets support stable demand, but allowed returns and capex needs limit high compounding.")
    if keyword_any(industry_text, ["银行", "保险", "金融", "证券", "信托", "资产管理"]) or keyword_any(lower_industry, ["bank", "insurance", "financial", "securities", "asset management"]):
        return IndustryOutlook(54, "macro_credit_cycle", "balance_sheet_compounding", "Financial companies can compound through risk control and distribution, but rates, credit, and capital markets create material cyclicality.")
    if keyword_any(industry_text, ["地产", "物业", "建筑", "建材"]) or keyword_any(lower_industry, ["properties", "property", "construction", "building materials"]):
        return IndustryOutlook(36, "deep_cyclical_or_structural_headwind", "limited_compounding", "Property-linked demand faces leverage, demographic, and investment-cycle pressure, so capital-heavy expansion deserves a low structural outlook.")
    if keyword_any(industry_text, ["零售", "百货", "超市", "贸易", "批发"]) or keyword_any(lower_industry, ["retail", "department store", "supermarket", "trading", "wholesale"]):
        return IndustryOutlook(44, "consumer_cycle_competitive", "weak_or_selective_compounding", "Generic retail and trading are usually replicable with capital and execution unless a company has clear platform or brand control.")
    if keyword_any(industry_text, ["博彩", "旅游", "酒店", "餐饮", "教育"]) or keyword_any(lower_industry, ["gaming", "tourism", "hotel", "restaurant", "leisure", "education"]):
        return IndustryOutlook(48, "demand_or_policy_cycle", "brand_location_compounding_if_leader", "Licenses, brands, or locations can matter, but tourism, gaming, education, and leisure depend on discretionary demand and policy settings.")
    if resource_leader_signal(industry_text, profile_text):
        return IndustryOutlook(64, "strategic_resource_cycle", "resource_and_process_compounding", "Commodity prices still create cycles, but scarce reserves, reserve replacement, low-cost development, and global mine integration can support leader-level compounding.")
    if keyword_any(industry_text, ["矿", "石油", "煤", "钢", "金属", "材料", "化工"]) or keyword_any(lower_industry, ["mining", "oil", "coal", "steel", "metal", "materials", "chemical"]):
        return IndustryOutlook(42, "commodity_cycle", "low_compounding", "Commodity and upstream materials earnings usually reflect price and capex cycles more than internally controlled compounding.")
    if keyword_any(profile_text, ["研发", "专利", "平台技术", "算法", "科技", "创新"]) or keyword_any(profile_text.lower(), ["research", "r&d", "patent", "algorithm", "technology", "innovation"]):
        return IndustryOutlook(56, "unclear_cycle_with_possible_innovation_tailwind", "selective_compounding", "Profile language suggests product or technology optionality, but industry evidence is too broad for a high structural-outlook score.")
    return IndustryOutlook(50, "unclear_cycle", "unproven_compounding", "Industry evidence does not support a clear structural tailwind or durable compounding profile beyond company-specific execution.")


def pct(percentiles: dict[str, float], code: str, default: float = 50.0) -> float:
    return percentiles.get(code, default)


def peer_position(score: float) -> str:
    if score >= 80:
        return "stronger_than_peers"
    if score >= 65:
        return "above_average"
    if score >= 45:
        return "average"
    if score >= 30:
        return "below_average"
    return "weak"


def watchlist_row(row: dict[str, str]) -> dict[str, str]:
    result = {
        "security_code": row["security_code"],
        "security_name": row["security_name"],
        "peer_group": row["peer_group"],
        "peer_relative_position": row["peer_relative_position"],
        "scoring_model_version": row["scoring_model_version"],
    }
    for output_column, label, source_column in WATCHLIST_SCORE_FIELDS:
        result[output_column] = f"{label}-{row[source_column]}"
    return result


def dedupe_watchlist_source_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    def preferred_row_key(row: dict[str, str]) -> tuple[float, int, str]:
        currency_rank = 0 if row.get("currency") == "HKD" else 1
        return (-float(row["weighted_total_score"]), currency_rank, row["security_code"])

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in sorted(rows, key=preferred_row_key):
        identity = row.get("isin") or row.get("listed_company_name") or row["security_code"]
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(row)
    selected.sort(key=lambda row: (-float(row["weighted_total_score"]), row["security_code"]))
    return selected


def source_join(*parts: str) -> str:
    urls: list[str] = []
    for part in parts:
        urls.extend(url for url in part.split(";") if url)
    return ";".join(dict.fromkeys(urls))


def score_row(
    raw: dict[str, str],
    profile: dict[str, str],
    financial: dict[str, str],
    percentiles: dict[str, dict[str, float]],
    reviewed_at: str,
) -> dict[str, str]:
    code = raw["security_code"]
    profile_status = profile.get("fetch_status")
    financial_status = financial.get("fetch_status")
    source_urls = source_join(profile.get("source_url", ""), financial.get("source_url", ""))
    industry = profile.get("industry") or raw.get("sub_category") or raw.get("category") or "unknown"
    peer_group = industry
    listing_date = profile.get("listing_date", "")
    profile_text = profile.get("company_profile", "")
    base = {
        "market_type": "HONG_KONG",
        "market_label": "港股",
        "security_code": code,
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "board": raw["board"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw.get("currency", ""),
        "isin": raw.get("isin", ""),
        "listing_date": listing_date,
        "industry": industry,
        "eligibility_status": "eligible",
        "peer_group": peer_group,
        "source_urls": source_urls,
        "reviewed_at_utc": reviewed_at,
        "scoring_model_version": SCORING_MODEL_VERSION,
    }
    if profile_status != "fetched":
        listed_at = parse_date(listing_date)
        newly_listed = bool(listed_at and (datetime.now(UTC).date() - listed_at).days < 365)
        status = "insufficient_disclosure" if newly_listed else "pending_research"
        base.update(
            {
                "screening_status": status,
                "disclosure_status": status,
                "peer_relative_position": "hard_to_distinguish",
                "overall_reason": "Awaiting fetched profile evidence; this is a workflow state unless the strict insufficient_disclosure definition applies.",
                "evidence_confidence": "low",
            }
        )
        for name, _ in DIMENSIONS:
            base[f"{name}_score"] = ""
            base[f"{name}_level"] = ""
            base[f"{name}_reason"] = ""
        base["weighted_total_score"] = ""
        base["overall_level"] = ""
        return base

    prior = industry_prior(peer_group, profile_text)
    outlook = industry_outlook(peer_group, profile_text)
    revenue_pct = pct(percentiles["total_operating_revenue"], code)
    profit_pct = pct(percentiles["parent_net_profit"], code)
    net_pct = pct(percentiles["net_margin_pct"], code)
    roe_pct = pct(percentiles["roe_weighted_pct"], code)
    debt_safety_pct = pct(percentiles["debt_asset_ratio_pct_inverse"], code)
    growth_pct = pct(percentiles["revenue_yoy_pct"], code)
    profit_growth_pct = pct(percentiles["profit_yoy_pct"], code)
    eps_pct = pct(percentiles["eps"], code)
    cash_pct = pct(percentiles["operating_cashflow_per_share"], code)

    keyword_bonus_moat = 0
    profile_text_lower = profile_text.lower()
    if keyword_any(profile_text, ["领先", "龙头", "最大", "独家", "特许", "牌照", "专营", "品牌", "全球"]) or keyword_any(profile_text_lower, ["leading", "largest", "exclusive", "license", "brand", "global"]):
        keyword_bonus_moat += 7
    if keyword_any(profile_text, ["用户", "会员", "客户", "网络", "平台"]) or keyword_any(profile_text_lower, ["user", "member", "customer", "network", "platform"]):
        keyword_bonus_moat += 4
    keyword_bonus_tech = 0
    if keyword_any(profile_text, ["研发", "专利", "算法", "云", "人工智能", "平台", "科技", "技术"]) or keyword_any(profile_text_lower, ["research", "r&d", "patent", "algorithm", "cloud", "artificial intelligence", " ai", "platform", "technology", "technical"]):
        keyword_bonus_tech += 8

    strategic_material = strategic_critical_material_signal(peer_group, profile_text)
    grid_core_equipment = grid_core_equipment_signal(peer_group, profile_text)
    capability_moat_bonus = 8 if strategic_material else 6 if grid_core_equipment else 0
    capability_market_bonus = 12 if strategic_material else 10 if grid_core_equipment else 0
    capability_tech_bonus = 10 if strategic_material else 8 if grid_core_equipment else 0

    business_moat = clamp(prior.business_moat + (revenue_pct - 50) * 0.10 + keyword_bonus_moat + capability_moat_bonus)
    technology_barrier = clamp(prior.technology_barrier + keyword_bonus_tech + capability_tech_bonus + (eps_pct - 50) * 0.04)
    market_position = clamp(45 + revenue_pct * 0.28 + profit_pct * 0.12 + (prior.business_moat - 50) * 0.25 + capability_market_bonus)
    business_quality = clamp(prior.business_quality + (net_pct - 50) * 0.14 + (growth_pct - 50) * 0.08 + (profit_growth_pct - 50) * 0.04)
    operating_quality = clamp(50 + (roe_pct - 50) * 0.18 + (cash_pct - 50) * 0.12 + (debt_safety_pct - 50) * 0.10)
    industry_outlook_score = clamp(outlook.score)
    governance_risk = clamp(70 + (debt_safety_pct - 50) * 0.06)
    weighted = weighted_score(
        {
            "business_moat": business_moat,
            "technology_barrier": technology_barrier,
            "market_position": market_position,
            "business_quality": business_quality,
            "operating_quality": operating_quality,
            "industry_outlook": industry_outlook_score,
            "governance_risk": governance_risk,
        }
    )

    confidence = "high" if financial_status == "fetched" and financial.get("total_operating_revenue") else "medium"
    base.update(
        {
            "screening_status": "scored",
            "disclosure_status": "sufficient_public_evidence",
            "peer_relative_position": peer_position(weighted),
            "cyclicality_profile": outlook.cyclicality_profile,
            "compounding_profile": outlook.compounding_profile,
            "business_moat_score": fmt_score(business_moat),
            "business_moat_level": level(business_moat),
            "business_moat_reason": f"Peer group {peer_group}; capability-first capital replicability view: {prior.capital_replicability}; revenue peer percentile is {revenue_pct:.0f}; current profit percentile {profit_pct:.0f} is recorded but not used directly in moat scoring; profile keywords add {keyword_bonus_moat} points and strategic capability adds {capability_moat_bonus} points.",
            "technology_barrier_score": fmt_score(technology_barrier),
            "technology_barrier_level": level(technology_barrier),
            "technology_barrier_reason": f"Technology prior comes from peer group and profile technology keywords; profile keywords add {keyword_bonus_tech} points, strategic-material/grid-equipment capability adds {capability_tech_bonus} points, and EPS percentile is {eps_pct:.0f}.",
            "market_position_score": fmt_score(market_position),
            "market_position_level": level(market_position),
            "market_position_reason": f"Market position uses reported revenue {financial.get('total_operating_revenue', '')} and net profit {financial.get('parent_net_profit', '')} relative to peer group percentiles {revenue_pct:.0f}/{profit_pct:.0f}, but current profit has lower weight in v0.4; strategic capability adds {capability_market_bonus} points.",
            "business_quality_score": fmt_score(business_quality),
            "business_quality_level": level(business_quality),
            "business_quality_reason": f"Business quality uses net margin {financial.get('net_margin_pct', '')}% revenue growth {financial.get('revenue_yoy_pct', '')}% and profit growth {financial.get('profit_yoy_pct', '')}% against peers, with lower weight than capability dimensions in v0.4.",
            "operating_quality_score": fmt_score(operating_quality),
            "operating_quality_level": level(operating_quality),
            "operating_quality_reason": f"Operating quality uses ROE {financial.get('roe_weighted_pct', '')}% operating cash flow per share {financial.get('operating_cashflow_per_share', '')} and debt ratio {financial.get('debt_asset_ratio_pct', '')}%; it constrains risk but no longer dominates the watchlist score in v0.4.",
            "industry_outlook_score": fmt_score(industry_outlook_score),
            "industry_outlook_level": level(industry_outlook_score),
            "industry_outlook_reason": outlook.reason,
            "governance_risk_score": fmt_score(governance_risk),
            "governance_risk_level": level(governance_risk),
            "governance_risk_reason": f"Governance and risk score starts from public disclosure availability and adjusts for balance-sheet pressure; fiscal year end is {profile.get('fiscal_year_end', '')}.",
            "weighted_total_score": fmt_score(weighted),
            "overall_level": level(weighted),
            "overall_reason": f"Weighted score from seven stored dimensions using the v0.4 capability-first weights, including industry outlook and cyclicality profile {outlook.cyclicality_profile}. This first-pass algorithmic score is evidence-backed by Eastmoney HKF10 profile and financial indicators.",
            "evidence_confidence": confidence,
        }
    )
    return base


def run(args: argparse.Namespace) -> tuple[int, int, int]:
    _, raw_rows = read_csv(args.raw)
    profiles = by_code(args.profiles)
    financials = by_code(args.financials)
    reviewed_at = utc_now()
    financial_rows = [
        financials[row["security_code"]] | {"peer_group": profiles.get(row["security_code"], {}).get("industry") or row.get("sub_category") or "unknown"}
        for row in raw_rows
        if financials.get(row["security_code"], {}).get("fetch_status") == "fetched"
    ]
    percentiles = {
        "total_operating_revenue": percentile_maps(financial_rows, "peer_group", "total_operating_revenue"),
        "parent_net_profit": percentile_maps(financial_rows, "peer_group", "parent_net_profit"),
        "net_margin_pct": percentile_maps(financial_rows, "peer_group", "net_margin_pct"),
        "roe_weighted_pct": percentile_maps(financial_rows, "peer_group", "roe_weighted_pct"),
        "debt_asset_ratio_pct_inverse": percentile_maps(financial_rows, "peer_group", "debt_asset_ratio_pct", reverse=True),
        "revenue_yoy_pct": percentile_maps(financial_rows, "peer_group", "revenue_yoy_pct"),
        "profit_yoy_pct": percentile_maps(financial_rows, "peer_group", "profit_yoy_pct"),
        "eps": percentile_maps(financial_rows, "peer_group", "eps"),
        "operating_cashflow_per_share": percentile_maps(financial_rows, "peer_group", "operating_cashflow_per_share"),
    }
    output_rows = [
        score_row(raw=row, profile=profiles.get(row["security_code"], {}), financial=financials.get(row["security_code"], {}), percentiles=percentiles, reviewed_at=reviewed_at)
        for row in raw_rows
    ]
    pending_count = sum(1 for row in output_rows if row["screening_status"] == "pending_research")
    if args.require_complete and pending_count:
        raise ScoringError(f"{pending_count} Hong Kong rows are still pending research evidence")
    write_csv(args.output, OUTPUT_COLUMNS, output_rows)
    watchlist_source_rows = [
        row
        for row in output_rows
        if row["screening_status"] == "scored" and row["weighted_total_score"] and float(row["weighted_total_score"]) >= args.candidate_threshold
    ]
    watchlist_source_rows = dedupe_watchlist_source_rows(watchlist_source_rows)
    watchlist_source_rows.sort(key=lambda row: (-float(row["weighted_total_score"]), row["security_code"]))
    watchlist_rows = [watchlist_row(row) for row in watchlist_source_rows]
    write_csv(args.watchlist, WATCHLIST_COLUMNS, watchlist_rows)
    return len(output_rows), sum(1 for row in output_rows if row["screening_status"] == "scored"), len(watchlist_rows)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Hong Kong full-coverage dimensional moat scoring.")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--candidate-threshold", type=int, default=70)
    parser.add_argument("--require-complete", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    total_count, scored_count, watchlist_count = run(args)
    print(f"Wrote {total_count} Hong Kong screening rows to {args.output}")
    print(f"Scored {scored_count} rows with fetched evidence")
    print(f"Wrote {watchlist_count} watchlist rows to {args.watchlist}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScoringError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

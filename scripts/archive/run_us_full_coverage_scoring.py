#!/usr/bin/env python3
"""Create dimensional U.S. moat scores from fetched SEC evidence."""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_RAW = Path("data/raw/us_securities.csv")
DEFAULT_QUEUE = Path("data/interim/us_research_queue.csv")
DEFAULT_PROFILES = Path("data/interim/us_company_profiles.csv")
DEFAULT_FINANCIALS = Path("data/interim/us_financial_indicators.csv")
DEFAULT_OUTPUT = Path("data/processed/us_full_coverage_scores.csv")
DEFAULT_WATCHLIST = Path("data/processed/us_full_coverage_watchlist.csv")
SCORING_MODEL_VERSION = "full_coverage_dimensional_v0.4"
MARKET_TYPE = "USA"
MARKET_LABEL = "美股"

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
    "market",
    "listed_company_name",
    "security_name",
    "currency",
    "asset_type_hint",
    "is_etf",
    "sec_cik",
    "sec_ticker",
    "security_eligibility",
    "eligibility_status",
    "screening_status",
    "disclosure_status",
    "listing_or_reporting_status",
    "industry",
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
    """Raised when U.S. full-coverage scoring inputs are invalid."""


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


def resource_leader_signal(peer_group: str, profile_text: str) -> bool:
    text = f"{peer_group} {profile_text}".lower()
    if not keyword_any(text, ["mining", "gold", "copper", "metal", "ore", "oil", "gas", "resource"]):
        return False
    signals = [
        keyword_any(text, ["global", "world", "international", "multi-national"]),
        keyword_any(text, ["reserves", "resources", "exploration", "acquisition", "portfolio"]),
        keyword_any(text, ["low-cost", "low grade", "low-grade", "mining engineering", "processing", "smelting", "integrated"]),
        keyword_any(text, ["leading", "largest", "top", "major producer"]),
    ]
    return sum(signals) >= 3


def strategic_critical_material_signal(peer_group: str, profile_text: str) -> bool:
    text = f"{peer_group} {profile_text}".lower()
    if not keyword_any(text, ["germanium", "gallium", "indium", "tungsten", "molybdenum", "antimony", "tantalum", "rare metal", "critical mineral", "compound semiconductor", "gallium arsenide", "indium phosphide"]):
        return False
    signals = [
        keyword_any(text, ["mine", "mining", "reserve", "resource", "exploration", "owned mine"]),
        keyword_any(text, ["purification", "wafer", "crystal", "infrared", "optical", "aerospace", "semiconductor material"]),
        keyword_any(text, ["national", "standard", "champion", "specialized", "proprietary", "patent"]),
        keyword_any(text, ["export control", "strategic resource", "supply security", "domestic substitution"]),
    ]
    return sum(signals) >= 2


def grid_core_equipment_signal(peer_group: str, profile_text: str) -> bool:
    text = f"{peer_group} {profile_text}".lower()
    if not keyword_any(text, ["power transmission", "transformer", "reactor", "mutual inductor", "high voltage", "ultra-high voltage", "uhv", "hvdc", "converter valve", "grid equipment"]):
        return False
    signals = [
        keyword_any(text, ["ultra-high voltage", "uhv", "hvdc", "converter valve", "first-of-a-kind"]),
        keyword_any(text, ["state grid", "national grid", "grid project", "demonstration project", "integrated solution"]),
        keyword_any(text, ["global leader", "world leading", "international leader", "leading market share"]),
        keyword_any(text, ["national", "technology center", "proprietary", "patent", "import substitution"]),
    ]
    return sum(signals) >= 2


def source_join(*parts: str) -> str:
    urls: list[str] = []
    for part in parts:
        urls.extend(url for url in part.split(";") if url)
    return ";".join(dict.fromkeys(urls))


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
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: (-float(item["weighted_total_score"]), item["security_code"])):
        identity = row.get("sec_cik") or row.get("listed_company_name") or row["security_code"]
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(row)
    selected.sort(key=lambda row: (-float(row["weighted_total_score"]), row["security_code"]))
    return selected


def infer_industry_from_name(raw: dict[str, str]) -> str:
    text = f"{raw.get('listed_company_name', '')} {raw.get('security_name', '')}".lower()
    if keyword_any(text, ["bank", "bancorp", "financial", "insurance", "capital"]):
        return "Banking and financial services"
    if keyword_any(text, ["biotech", "therapeutics", "pharma", "medical", "health"]):
        return "Healthcare and biotechnology"
    if keyword_any(text, ["software", "technology", "semiconductor", "ai ", "data", "systems"]):
        return "Technology"
    if keyword_any(text, ["energy", "oil", "gas", "mining", "gold", "uranium"]):
        return "Energy and materials"
    if keyword_any(text, ["restaurant", "food", "beverage", "consumer", "apparel"]):
        return "Consumer"
    if keyword_any(text, ["acquisition corp", "acquisition corporation", "blank check"]):
        return "Blank check company"
    return "Unknown"


def industry_prior(peer_group: str, profile_text: str, security_name: str) -> IndustryPrior:
    text = f"{peer_group} {profile_text} {security_name}".lower()
    if keyword_any(text, ["acquisition corp", "blank check", "special purpose acquisition"]):
        return IndustryPrior(20, 20, 20, "blank-check companies have no operating moat until an operating business is acquired")
    if strategic_critical_material_signal(peer_group, profile_text):
        return IndustryPrior(74, 82, 58, "strategic scarce materials combine resource access, purification, crystal or compound processing, standards, and customer qualification that capital alone cannot compress quickly")
    if grid_core_equipment_signal(peer_group, profile_text):
        return IndustryPrior(72, 78, 62, "ultra-high-voltage grid equipment requires long engineering accumulation, safety validation, grid qualification, and project references that capital alone cannot buy quickly")
    if keyword_any(text, ["bank", "national commercial banks", "state commercial banks", "savings institution", "credit institution"]):
        return IndustryPrior(72, 45, 64, "banking licenses deposits customer relationships and risk systems reduce pure capital replicability")
    if keyword_any(text, ["finance services", "financial services", "insurance", "broker", "investment advice", "security brokers", "asset management"]):
        return IndustryPrior(68, 48, 62, "licenses distribution trust and risk underwriting matter but capital can still compete in parts of finance")
    if resource_leader_signal(peer_group, profile_text):
        return IndustryPrior(66, 68, 56, "scarce resource base global portfolio exploration M&A integration and mining or upstream engineering know-how reduce pure capital replicability despite commodity exposure")
    if keyword_any(text, ["crude petroleum", "oil & gas", "oil", "mining", "coal", "steel", "chemical", "metals", "paper", "gold", "silver", "ores", "uranium", "copper"]):
        return IndustryPrior(54, 58, 50, "resource cost scale process assets and cycles matter but commodity exposure lowers durability")
    if keyword_any(text, ["electric services", "electric & other services", "natural gas transmission", "natural gas distribution", "gas transmission", "water supply", "utility", "pipeline", "railroad", "telephone communications", "telecommunications"]):
        return IndustryPrior(78, 45, 72, "regulated networks concessions and infrastructure assets are hard to replicate quickly with capital alone")
    if keyword_any(text, ["semiconductor", "electronic computers", "computer storage", "electronic components", "communications equipment"]):
        return IndustryPrior(66, 80, 60, "design capability process know-how supply-chain qualification and customer validation take time")
    if keyword_any(text, ["prepackaged software", "software", "data processing", "information retrieval", "internet", "cloud", "platform"]):
        return IndustryPrior(70, 74, 64, "software platforms data ecosystems and switching costs can resist capital-only entry")
    if keyword_any(text, ["pharmaceutical", "biological", "medical", "surgical", "diagnostic", "therapeutics", "biotechnology"]):
        return IndustryPrior(65, 78, 60, "clinical validation patents regulation and physician or customer trust limit fast capital replication")
    if keyword_any(text, ["aerospace", "aircraft", "defense", "guided missiles"]):
        return IndustryPrior(70, 74, 62, "certification defense relationships engineering depth and manufacturing qualification are slow to replicate")
    if keyword_any(text, ["machinery", "equipment", "instruments", "industrial", "motor vehicle", "electrical machinery", "manufacturing"]):
        return IndustryPrior(55, 66, 55, "engineering experience supply-chain execution and customer qualification matter but many capacity additions are cyclical")
    if keyword_any(text, ["food", "beverage", "tobacco", "cosmetics", "apparel", "restaurants"]):
        return IndustryPrior(72, 45, 68, "brands distribution store base and customer habit are costly but not impossible to replicate")
    if keyword_any(text, ["retail", "grocery", "department stores", "catalog", "mail-order"]):
        return IndustryPrior(46, 38, 48, "retail formats inventory and stores are comparatively replicable with capital and execution")
    if keyword_any(text, ["real estate", "reit", "construction", "homebuilding", "building"]):
        return IndustryPrior(45, 40, 42, "asset access and execution matter but leverage and capital availability drive much of the structure")
    if keyword_any(text, ["crude petroleum", "oil & gas", "oil", "mining", "coal", "steel", "chemical", "metals", "paper", "gold", "silver", "ores", "uranium", "copper"]):
        return IndustryPrior(54, 58, 50, "resource cost scale process assets and cycles matter but commodity exposure lowers durability")
    if keyword_any(text, ["air transportation", "airlines", "hotel", "casino", "cruise", "travel"]):
        return IndustryPrior(50, 42, 46, "brand route slots locations or licenses matter but cyclical demand and capital intensity reduce durability")
    if keyword_any(text, ["patent", "research", "algorithm", "technology", "engineering"]):
        return IndustryPrior(55, 64, 52, "profile suggests technical capability but the industry classification is broad")
    return IndustryPrior(50, 50, 50, "SEC industry evidence does not show a clearly hard-to-replicate structure")


def industry_outlook(peer_group: str, profile_text: str, security_name: str) -> IndustryOutlook:
    text = f"{peer_group} {profile_text} {security_name}".lower()
    if keyword_any(text, ["acquisition corp", "blank check", "special purpose acquisition"]):
        return IndustryOutlook(20, "no_operating_business", "not_applicable", "Blank-check companies do not yet have an operating industry outlook or compounding engine to score as listed operating businesses.")
    if strategic_critical_material_signal(peer_group, profile_text):
        return IndustryOutlook(72, "strategic_critical_material_cycle", "resource_technology_optionality", "Strategic scarce materials can benefit from semiconductors, aerospace, AI infrastructure, optical communication, and supply-security demand; price cycles and capacity ramp risks still keep the score below elite compounders.")
    if grid_core_equipment_signal(peer_group, profile_text):
        return IndustryOutlook(68, "grid_capex_structural_growth", "installed_base_and_engineering_compounding", "Grid modernization, UHV transmission, renewable power integration, and overseas power-infrastructure demand support long-cycle growth, though customer capex cycles and project timing remain material.")
    if keyword_any(text, ["prepackaged software", "software", "data processing", "information retrieval", "internet", "cloud", "platform", "artificial intelligence"]):
        return IndustryOutlook(80, "low_to_moderate_cyclicality", "compound_growth", "Cloud, AI, data, and software adoption support multi-year demand, while retention, ecosystem depth, and switching costs separate durable compounders.")
    if keyword_any(text, ["semiconductor", "electronic computers", "computer storage", "electronic components", "communications equipment", "networking"]):
        return IndustryOutlook(74, "cyclical_structural_growth", "innovation_compounding", "AI infrastructure, data centers, and connected devices support demand, but chip and hardware cycles remain material.")
    if keyword_any(text, ["pharmaceutical", "biological", "medical", "surgical", "diagnostic", "therapeutics", "biotechnology"]):
        return IndustryOutlook(70, "defensive_growth_with_binary_risk", "innovation_or_brand_compounding", "Aging, healthcare demand, and medical innovation support growth, but patents, clinical outcomes, reimbursement, and regulation create uneven results.")
    if keyword_any(text, ["aerospace", "aircraft", "defense", "guided missiles"]):
        return IndustryOutlook(68, "defense_capex_cycle", "long_backlog_compounding", "Defense and aerospace demand can benefit from long backlogs and geopolitics, but budgets, programs, and certification cycles limit smooth compounding.")
    if keyword_any(text, ["food", "beverage", "tobacco", "cosmetics"]):
        return IndustryOutlook(72, "low_cyclicality", "brand_compounding", "Consumer staples and trusted brands can compound through pricing, distribution, and habit with less macro sensitivity.")
    if keyword_any(text, ["restaurants", "apparel", "retail", "grocery", "department stores", "catalog", "mail-order"]):
        return IndustryOutlook(48, "consumer_cycle_competitive", "weak_or_selective_compounding", "Retail, restaurants, and apparel are easier to replicate with capital and execution unless a company has unusually strong brand, scale, or data advantages.")
    if resource_leader_signal(peer_group, profile_text):
        return IndustryOutlook(64, "strategic_resource_cycle", "resource_and_process_compounding", "Commodity prices still create cycles, but scarce reserves, reserve replacement, low-cost development, and global asset integration can support leader-level compounding.")
    if keyword_any(text, ["crude petroleum", "oil & gas", "oil", "mining", "coal", "steel", "chemical", "metals", "paper", "gold", "silver", "ores", "uranium", "copper"]):
        return IndustryOutlook(42, "commodity_cycle", "low_compounding", "Commodity and upstream material returns are often driven by prices and capex cycles more than internally controlled compounding.")
    if keyword_any(text, ["electric services", "electric & other services", "natural gas transmission", "natural gas distribution", "gas transmission", "water supply", "utility", "pipeline", "railroad", "telephone communications", "telecommunications"]):
        return IndustryOutlook(62, "low_cyclicality", "regulated_stable_compounding", "Regulated networks and infrastructure can create stable demand, but allowed returns and capital intensity limit high compounding.")
    if keyword_any(text, ["finance services", "financial services", "bank", "national commercial banks", "state commercial banks", "savings institution", "credit institution", "insurance", "broker", "investment advice", "security brokers", "asset management"]):
        return IndustryOutlook(54, "macro_credit_or_market_cycle", "balance_sheet_compounding", "Financial companies can compound through risk control and distribution, but rates, credit, and capital markets create material cyclicality.")
    if keyword_any(text, ["real estate", "reit", "construction", "homebuilding", "building"]):
        return IndustryOutlook(40, "property_or_rate_cycle", "limited_or_asset_compounding", "Real estate and construction are tied to rates, leverage, and construction cycles, so growth is often less durable than asset-light compounders.")
    if keyword_any(text, ["crude petroleum", "oil & gas", "oil", "mining", "coal", "steel", "chemical", "metals", "paper", "gold", "silver", "ores", "uranium", "copper"]):
        return IndustryOutlook(42, "commodity_cycle", "low_compounding", "Commodity and upstream material returns are often driven by prices and capex cycles more than internally controlled compounding.")
    if keyword_any(text, ["air transportation", "airlines", "hotel", "casino", "cruise", "travel", "transportation", "freight", "shipping"]):
        return IndustryOutlook(45, "demand_cycle_high_operating_leverage", "brand_location_compounding_if_leader", "Travel and leisure demand can recover strongly, but fuel, labor, discretionary demand, and operating leverage reduce compounding quality.")
    if keyword_any(text, ["machinery", "equipment", "instruments", "industrial", "motor vehicle", "electrical machinery", "manufacturing"]):
        return IndustryOutlook(58, "capex_cycle", "selective_compounding", "Equipment and industrial manufacturing demand follows customer capex and inventory cycles; installed-base service and specialized know-how separate durable leaders.")
    if keyword_any(text, ["patent", "research", "algorithm", "technology", "engineering"]):
        return IndustryOutlook(56, "unclear_cycle_with_possible_innovation_tailwind", "selective_compounding", "Profile text suggests technology optionality, but the industry evidence is too broad for a high structural-outlook score.")
    return IndustryOutlook(50, "unclear_cycle", "unproven_compounding", "Industry evidence does not support a clear structural tailwind or durable compounding profile beyond company-specific execution.")


def pct(percentiles: dict[str, float], code: str, default: float = 50.0) -> float:
    return percentiles.get(code, default)


def base_row(raw: dict[str, str], profile: dict[str, str], queue: dict[str, str], reviewed_at: str) -> dict[str, str]:
    return {
        "market_type": MARKET_TYPE,
        "market_label": MARKET_LABEL,
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "market": raw["market"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw["currency"],
        "asset_type_hint": raw.get("asset_type_hint", ""),
        "is_etf": raw.get("is_etf", ""),
        "sec_cik": profile.get("sec_cik", ""),
        "sec_ticker": profile.get("sec_ticker", ""),
        "security_eligibility": queue.get("security_eligibility", ""),
        "industry": profile.get("sic_description") or infer_industry_from_name(raw),
        "peer_group": profile.get("sic_description") or infer_industry_from_name(raw),
        "source_urls": source_join(profile.get("source_url", "")),
        "reviewed_at_utc": reviewed_at,
        "scoring_model_version": SCORING_MODEL_VERSION,
    }


def blank_dimension_fields(row: dict[str, str]) -> None:
    for name, _ in DIMENSIONS:
        row[f"{name}_score"] = ""
        row[f"{name}_level"] = ""
        row[f"{name}_reason"] = ""
    row["weighted_total_score"] = ""
    row["overall_level"] = ""


def financial_metric_count(financial: dict[str, str]) -> int:
    fields = [
        "revenue",
        "net_income",
        "operating_cash_flow",
        "assets",
        "liabilities",
        "stockholders_equity",
        "gross_margin_pct",
        "roe_pct",
    ]
    return sum(1 for field in fields if financial.get(field))


def score_row(
    raw: dict[str, str],
    profile: dict[str, str],
    financial: dict[str, str],
    queue: dict[str, str],
    percentiles: dict[str, dict[str, float]],
    reviewed_at: str,
) -> dict[str, str]:
    code = raw["security_code"]
    row = base_row(raw, profile, queue, reviewed_at)
    row["source_urls"] = source_join(profile.get("source_url", ""), financial.get("source_url", ""))

    if queue.get("security_eligibility") != "eligible_common_equity":
        row.update(
            {
                "eligibility_status": "not_eligible",
                "screening_status": "not_eligible_non_company_security",
                "disclosure_status": "not_applicable",
                "listing_or_reporting_status": queue.get("security_eligibility_reason", ""),
                "peer_relative_position": "hard_to_distinguish",
                "overall_reason": "Excluded from company moat scoring because the raw U.S. security is not a common-equity company instrument.",
                "evidence_confidence": "medium",
            }
        )
        blank_dimension_fields(row)
        return row

    if profile.get("fetch_status") != "fetched":
        row.update(
            {
                "eligibility_status": "eligible",
                "screening_status": "pending_research",
                "disclosure_status": "pending_research",
                "listing_or_reporting_status": "SEC or fallback profile evidence unavailable",
                "peer_relative_position": "hard_to_distinguish",
                "overall_reason": "Awaiting profile evidence; this is a workflow state, not evidence insufficiency.",
                "evidence_confidence": "low",
            }
        )
        blank_dimension_fields(row)
        return row

    profile_text = " ".join(
        part
        for part in [
            profile.get("sic_description", ""),
            profile.get("description", ""),
            profile.get("owner_org", ""),
            raw.get("security_name", ""),
        ]
        if part
    )
    peer_group = profile.get("sic_description") or infer_industry_from_name(raw)
    row["industry"] = peer_group
    row["peer_group"] = peer_group
    prior = industry_prior(peer_group, profile_text, raw.get("security_name", ""))
    outlook = industry_outlook(peer_group, profile_text, raw.get("security_name", ""))

    revenue_pct = pct(percentiles["revenue"], code)
    net_income_pct = pct(percentiles["net_income"], code)
    gross_margin_pct = pct(percentiles["gross_margin_pct"], code)
    net_margin_pct = pct(percentiles["net_margin_pct"], code)
    operating_margin_pct = pct(percentiles["operating_margin_pct"], code)
    roe_pct = pct(percentiles["roe_pct"], code)
    cashflow_pct = pct(percentiles["operating_cashflow_to_revenue_pct"], code)
    debt_safety_pct = pct(percentiles["debt_asset_ratio_pct_inverse"], code)
    rd_pct = pct(percentiles["rd_to_revenue_pct"], code)
    growth_pct = pct(percentiles["revenue_yoy_pct"], code)
    eps_pct = pct(percentiles["eps_diluted"], code)

    keyword_bonus_moat = 0
    if keyword_any(profile_text, ["leading", "largest", "exclusive", "license", "patent", "brand", "network", "platform"]):
        keyword_bonus_moat += 7
    if keyword_any(profile_text, ["customer", "subscription", "installed base", "ecosystem", "data"]):
        keyword_bonus_moat += 4

    keyword_bonus_tech = 0
    if keyword_any(profile_text, ["research", "patent", "algorithm", "cloud", "artificial intelligence", "semiconductor", "biotechnology", "engineering"]):
        keyword_bonus_tech += 8

    metric_count = financial_metric_count(financial)
    financial_penalty = 0 if metric_count >= 4 else 8 if metric_count >= 2 else 16
    reporting_penalty = 0
    if raw.get("financial_status") in {"D", "E", "H"}:
        reporting_penalty = 18

    strategic_material = strategic_critical_material_signal(peer_group, profile_text)
    grid_core_equipment = grid_core_equipment_signal(peer_group, profile_text)
    capability_moat_bonus = 8 if strategic_material else 6 if grid_core_equipment else 0
    capability_market_bonus = 12 if strategic_material else 10 if grid_core_equipment else 0
    capability_tech_bonus = 10 if strategic_material else 8 if grid_core_equipment else 0

    business_moat = clamp(prior.business_moat + (revenue_pct - 50) * 0.10 + keyword_bonus_moat + capability_moat_bonus)
    technology_barrier = clamp(prior.technology_barrier + (rd_pct - 50) * 0.10 + (eps_pct - 50) * 0.03 + keyword_bonus_tech + capability_tech_bonus)
    market_position = clamp(45 + revenue_pct * 0.28 + net_income_pct * 0.12 + (prior.business_moat - 50) * 0.25 + capability_market_bonus)
    business_quality = clamp(prior.business_quality + (gross_margin_pct - 50) * 0.12 + (net_margin_pct - 50) * 0.10 + (operating_margin_pct - 50) * 0.06 + (growth_pct - 50) * 0.06 - financial_penalty * 0.35)
    operating_quality = clamp(50 + (roe_pct - 50) * 0.16 + (cashflow_pct - 50) * 0.14 + (debt_safety_pct - 50) * 0.10 - financial_penalty * 0.5)
    industry_outlook_score = clamp(outlook.score)
    governance_risk = clamp(72 + (debt_safety_pct - 50) * 0.06 - reporting_penalty)
    if keyword_any(profile_text, ["blank check", "acquisition corp"]):
        business_moat = min(business_moat, 35)
        technology_barrier = min(technology_barrier, 35)
        market_position = min(market_position, 35)
        business_quality = min(business_quality, 35)
        operating_quality = min(operating_quality, 35)
        industry_outlook_score = min(industry_outlook_score, 20)

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
    confidence = "high" if profile.get("source_provider") == "SEC EDGAR" and metric_count >= 4 else "medium" if metric_count else "low"

    row.update(
        {
            "eligibility_status": "eligible",
            "screening_status": "scored",
            "disclosure_status": "sufficient_public_evidence",
            "listing_or_reporting_status": raw.get("financial_status", "") or "listed",
            "peer_relative_position": peer_position(weighted),
            "cyclicality_profile": outlook.cyclicality_profile,
            "compounding_profile": outlook.compounding_profile,
            "business_moat_score": fmt_score(business_moat),
            "business_moat_level": level(business_moat),
            "business_moat_reason": f"Peer group {peer_group}; capability-first capital replicability view: {prior.capital_replicability}; SEC revenue peer percentile is {revenue_pct:.0f}; current net income percentile {net_income_pct:.0f} is recorded but not used directly in moat scoring; profile keywords add {keyword_bonus_moat} points and strategic capability adds {capability_moat_bonus} points.",
            "technology_barrier_score": fmt_score(technology_barrier),
            "technology_barrier_level": level(technology_barrier),
            "technology_barrier_reason": f"Technology prior comes from SEC SIC/profile text; R&D-to-revenue and EPS peer percentiles are {rd_pct:.0f}/{eps_pct:.0f}; profile technology keywords add {keyword_bonus_tech} points and strategic-material/grid-equipment capability adds {capability_tech_bonus} points.",
            "market_position_score": fmt_score(market_position),
            "market_position_level": level(market_position),
            "market_position_reason": f"Market position uses SEC companyfacts revenue {financial.get('revenue', '')} and net income {financial.get('net_income', '')} relative to peer percentiles {revenue_pct:.0f}/{net_income_pct:.0f}, but current net income has lower weight in v0.4; strategic capability adds {capability_market_bonus} points.",
            "business_quality_score": fmt_score(business_quality),
            "business_quality_level": level(business_quality),
            "business_quality_reason": f"Business quality uses gross margin {financial.get('gross_margin_pct', '')}% net margin {financial.get('net_margin_pct', '')}% operating margin {financial.get('operating_margin_pct', '')}% and revenue growth {financial.get('revenue_yoy_pct', '')}% against peers, with lower weight than capability dimensions in v0.4.",
            "operating_quality_score": fmt_score(operating_quality),
            "operating_quality_level": level(operating_quality),
            "operating_quality_reason": f"Operating quality uses ROE {financial.get('roe_pct', '')}% operating-cash-flow-to-revenue {financial.get('operating_cashflow_to_revenue_pct', '')}% and debt/assets {financial.get('debt_asset_ratio_pct', '')}%; missing metric penalty is {financial_penalty}. It constrains risk but no longer dominates the watchlist score in v0.4.",
            "industry_outlook_score": fmt_score(industry_outlook_score),
            "industry_outlook_level": level(industry_outlook_score),
            "industry_outlook_reason": outlook.reason,
            "governance_risk_score": fmt_score(governance_risk),
            "governance_risk_level": level(governance_risk),
            "governance_risk_reason": f"Governance and disclosure score starts from SEC reporting availability and adjusts for balance-sheet pressure and Nasdaq financial status {raw.get('financial_status', '') or 'not provided'}.",
            "weighted_total_score": fmt_score(weighted),
            "overall_level": level(weighted),
            "overall_reason": f"Weighted score from seven stored dimensions using the v0.4 capability-first weights, including industry outlook and cyclicality profile {outlook.cyclicality_profile}. This first-pass algorithmic score is backed by Nasdaq Trader universe data plus SEC EDGAR profile and companyfacts evidence where available.",
            "evidence_confidence": confidence,
        }
    )
    return row


def run(args: argparse.Namespace) -> tuple[int, int, int, int]:
    _, raw_rows = read_csv(args.raw)
    queues = by_code(args.queue)
    profiles = by_code(args.profiles)
    financials = by_code(args.financials)
    reviewed_at = utc_now()
    financial_rows = []
    for row in raw_rows:
        code = row["security_code"]
        queue = queues.get(code, {})
        if queue.get("security_eligibility") != "eligible_common_equity":
            continue
        financial = financials.get(code, {})
        if financial.get("fetch_status") not in {"fetched", "not_available"}:
            continue
        profile = profiles.get(code, {})
        peer_group = profile.get("sic_description") or infer_industry_from_name(row)
        financial_rows.append(financial | {"peer_group": peer_group})

    percentiles = {
        "revenue": percentile_maps(financial_rows, "peer_group", "revenue"),
        "net_income": percentile_maps(financial_rows, "peer_group", "net_income"),
        "gross_margin_pct": percentile_maps(financial_rows, "peer_group", "gross_margin_pct"),
        "operating_margin_pct": percentile_maps(financial_rows, "peer_group", "operating_margin_pct"),
        "net_margin_pct": percentile_maps(financial_rows, "peer_group", "net_margin_pct"),
        "roe_pct": percentile_maps(financial_rows, "peer_group", "roe_pct"),
        "operating_cashflow_to_revenue_pct": percentile_maps(financial_rows, "peer_group", "operating_cashflow_to_revenue_pct"),
        "debt_asset_ratio_pct_inverse": percentile_maps(financial_rows, "peer_group", "debt_asset_ratio_pct", reverse=True),
        "rd_to_revenue_pct": percentile_maps(financial_rows, "peer_group", "rd_to_revenue_pct"),
        "revenue_yoy_pct": percentile_maps(financial_rows, "peer_group", "revenue_yoy_pct"),
        "eps_diluted": percentile_maps(financial_rows, "peer_group", "eps_diluted"),
    }

    output_rows = [
        score_row(
            raw=row,
            profile=profiles.get(row["security_code"], {}),
            financial=financials.get(row["security_code"], {}),
            queue=queues.get(row["security_code"], {}),
            percentiles=percentiles,
            reviewed_at=reviewed_at,
        )
        for row in raw_rows
    ]
    pending_count = sum(1 for row in output_rows if row["screening_status"] == "pending_research")
    if args.require_complete and pending_count:
        raise ScoringError(f"{pending_count} U.S. rows are still pending research evidence")

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
    return (
        len(output_rows),
        sum(1 for row in output_rows if row["screening_status"] == "scored"),
        sum(1 for row in output_rows if row["screening_status"] == "not_eligible_non_company_security"),
        len(watchlist_rows),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run U.S. full-coverage dimensional moat scoring.")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
    parser.add_argument("--candidate-threshold", type=int, default=70)
    parser.add_argument("--require-complete", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    total_count, scored_count, not_eligible_count, watchlist_count = run(args)
    print(f"Wrote {total_count} U.S. screening rows to {args.output}")
    print(f"Scored {scored_count} rows with fetched evidence")
    print(f"Marked {not_eligible_count} rows as non-company/common-equity ineligible")
    print(f"Wrote {watchlist_count} watchlist rows to {args.watchlist}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScoringError as exc:
        print(f"error: {exc}")
        raise SystemExit(1)

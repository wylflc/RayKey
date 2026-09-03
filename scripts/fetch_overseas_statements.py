#!/usr/bin/env python3
"""海外关注清单（§6.8）的三大报表取数 → ROIC 口径逐年输入（与 A 股 `roic_inputs.RoicYear` 同字段）。

来源（2026-08-23 起，用户指令「海外公司同样应用当前估值方法」）：
* 美股／美元 ADR：SEC XBRL companyfacts（`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`），按 CIK
  取年度值及最新 10-Q；季报按「最近完整财年 + 本期累计 − 上年同期累计」合成 TTM。
  同一期末取**最新申报**（含重述）。US-GAAP 与 IFRS（20-F）两套标签都映射。
* 港股：东财 HK F10 三张表（`RPT_HKF10_FN_{BALANCE,INCOME,CASHFLOW}_PC`），年度值加最新季报／中报，
  同样合成 TTM。
  报表货币按公司（清单内人民币列报公司显式登记）。股数取 `hong_kong_financial_indicators.csv` 最新已发行股数。
* 6-K／境外发行人季报不进入 SEC companyfacts 的公司，由官方财报逐项维护
  `data/reference/overseas_statement_overrides.csv`；披露事件与公开可得日只认
  `data/reference/overseas_report_evidence.csv`，不拿程序运行日或预期财报日代替证据日。
* 韩股：无免密钥三表源——不出行，清单上保持「无法估值」并写明缺口（§6.5.2.4）。
原始 JSON 落 `data/raw/overseas_statements/`（不入库，≈4 MB/家）；提取结果落 `data/interim/overseas_roic_years.csv`（入库）。

字段口径与 `roic_inputs.load_statements` 逐项对齐：
  ebit = 除税前溢利 + 利息费用；tax_rate = 所得税/除税前溢利（利润非正回退市场法定税率，夹 [0,40%]）；
  nopat = ebit×(1−t)；excess_cash = max(0, 现金类 − 2%×营收)；invested_capital = 有息负债 + 总权益 − 超额现金。
  §6.5.2.3 股本口径用的留存项：net_income = 归母净利、tci = 归母综合收益（年度与 TTM 均为区间值）；
  TTM 行另给 net_income_ytd／dividends_paid_ytd = 最新年报期末之后的本财年累计值（年报行留空；季报现金流量表无已付股息行时，
  上一财年未付股息的公司记 0，付过股息的公司改由分红事件表折算——见下）。
  补缺源（东财数据中心，原始 JSON 同样落 `data/raw/overseas_statements/`）：
  * 港股现金流量表缺「已付股息」行（东财 F10 部分中报只给摘要、阿里巴巴年报也只有 8 行）→ `RPT_HKF10_INFO_DIVIDEND` 分红事件，
    除净日落在 (上期期末, 本期期末] 的现金分派按「每股派 × 最新已发行股数」折成报表币（`overseas_valuation_inputs.csv` 汇率）；
  * `overseas_statement_overrides.csv` 维护行未填归母净利／综合收益／年报后累计值 → `RPT_USF10_FN_INCOME`（归属于母公司股东净利润、
    本公司拥有人占全面收益总额，报表币）与 `RPT_USF10_INFO_DIVIDEND`（每 ADR 美元派息 ÷ 每 ADR 股数 × 股数 × 汇率）。
  补缺来源都写进 `tags_used`（`eastmoney:` 前缀）。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs  # noqa: E402

WATCHLIST = ROOT / "data/processed/overseas_watchlist_valuation.csv"
US_INDICATORS = ROOT / "data/interim/us_financial_indicators.csv"
HK_INDICATORS = ROOT / "data/interim/hong_kong_financial_indicators.csv"
RAW_DIR = ROOT / "data/raw/overseas_statements"
OUT = ROOT / "data/interim/overseas_roic_years.csv"
REPORT_EVIDENCE = ROOT / "data/reference/overseas_report_evidence.csv"
STATEMENT_OVERRIDES = ROOT / "data/reference/overseas_statement_overrides.csv"
VALUATION_INPUTS = ROOT / "data/reference/overseas_valuation_inputs.csv"
UA = "RayKey-AShareQuant research bot (personal research use)"
HK_API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
# 港股清单的报表货币（东财 HK F10 不带币种列；人民币列报公司显式登记）
HK_REPORT_CCY = {"00700": "CNY", "09992": "CNY", "09618": "CNY", "09988": "CNY", "03690": "CNY", "06862": "CNY",
                 "03888": "CNY", "00316": "CNY", "00267": "CNY"}
TAX_DEFAULT = {"US": 0.21, "HK": 0.165}

FIELDS = ["market", "security_code", "security_name", "period", "fiscal_year", "notice_date", "report_currency",
          "revenue", "operating_income", "pretax", "income_tax", "interest_expense", "ebit", "tax_rate", "tax_rate_observed",
          "nopat", "total_equity", "parent_equity", "minority_equity", "interest_debt", "cash_like", "excess_cash",
          "invested_capital", "capex", "dep_amort", "cfo", "shares", "buybacks", "dividends_paid",
          "net_income", "tci", "net_income_ytd", "dividends_paid_ytd", "tags_used", "source"]

PERIOD_META_FIELDS = ["period_type", "report_label", "evidence_url"]
FIELDS += PERIOD_META_FIELDS

GAAP = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"],
    "total_equity": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"],
    "parent_equity": ["StockholdersEquity"],
    "minority_equity": ["MinorityInterest"],
    "lt_debt_noncurrent": ["LongTermDebtNoncurrent"],
    "lt_debt_current": ["LongTermDebtCurrent"],
    "lt_debt_total": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
    "st_debt": ["ShortTermBorrowings", "CommercialPaper", "DebtCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "cash_invest": ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                    "DebtSecuritiesCurrent"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dep_amort": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                  "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
    "shares_instant": ["CommonStockSharesOutstanding"],
    # OI-082：回购与分红现金流（回购用于权益回加，分红只作展示）
    "buybacks": ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "PaymentsOfOrdinaryDividends"],
    # §6.5.2.3 股本口径：年报间外生权益 X_y = ΔE − (归母综合收益 − 已付股息)，综合收益缺失用归母净利；季报观察点 x 用其后归母净利
    "net_income": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
    "tci": ["ComprehensiveIncomeNetOfTax", "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest"],
}
IFRS = {
    "revenue": ["Revenue", "RevenueFromSaleOfGoods", "RevenueFromContractsWithCustomers"],
    "operating_income": ["ProfitLossFromOperatingActivities"],
    "pretax": ["ProfitLossBeforeTax"],
    "income_tax": ["IncomeTaxExpenseContinuingOperations"],
    "interest_expense": ["InterestExpense", "FinanceCosts"],
    "total_equity": ["Equity"],
    "parent_equity": ["EquityAttributableToOwnersOfParent"],
    "minority_equity": ["NoncontrollingInterests"],
    "lt_debt_noncurrent": ["NoncurrentPortionOfNoncurrentBorrowings", "LongtermBorrowings", "NoncurrentPortionOfNoncurrentBondsIssued"],
    "lt_debt_current": ["CurrentPortionOfLongtermBorrowings", "CurrentPortionOfNoncurrentBondsIssued"],
    "lt_debt_total": ["Borrowings", "BondsIssued"],
    "st_debt": ["ShorttermBorrowings", "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"],
    "cash": ["CashAndCashEquivalents"],
    "cash_invest": ["CurrentFinancialAssetsAtFairValueThroughProfitOrLoss", "OtherCurrentFinancialAssets"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "dep_amort": ["DepreciationAndAmortisationExpense", "DepreciationPropertyPlantAndEquipment"],
    "cfo": ["CashFlowsFromUsedInOperatingActivities"],
    "shares": ["AdjustedWeightedAverageShares", "WeightedAverageShares"],
    "shares_instant": ["NumberOfSharesOutstanding", "NumberOfSharesIssued"],
    "buybacks": ["PaymentsToAcquireOrRedeemEntitysShares"],
    "dividends_paid": ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],
    "net_income": ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
    "tci": ["ComprehensiveIncomeAttributableToOwnersOfParent", "ComprehensiveIncome"],
}
DURATION = {"revenue", "operating_income", "pretax", "income_tax", "interest_expense", "capex", "dep_amort", "cfo", "shares", "buybacks", "dividends_paid",
            "net_income", "tci"}
HK_ITEMS = {
    "revenue": ("income", ["营业额", "营运收入"]),
    "operating_income": ("income", ["经营溢利"]),
    "pretax": ("income", ["除税前溢利"]),
    "income_tax": ("income", ["税项"]),
    "interest_expense": ("income", ["融资成本"]),
    "total_equity": ("balance", ["总权益"]),
    "parent_equity": ("balance", ["股东权益"]),
    "minority_equity": ("balance", ["少数股东权益"]),
    "lt_loan": ("balance", ["长期贷款"]),
    "st_loan": ("balance", ["短期贷款"]),
    "notes_nc": ("balance", ["应付票据(非流动)"]),
    "notes_c": ("balance", ["应付票据"]),
    "bonds": ("balance", ["应付债券"]),
    "convertibles": ("balance", ["可转换票据及债券", "可转换债券及票据"]),
    "lease_nc": ("balance", ["融资租赁负债(非流动)"]),
    "lease_c": ("balance", ["融资租赁负债(流动)"]),
    "cash": ("balance", ["现金及等价物"]),
    "deposits": ("balance", ["短期存款"]),
    "capex": ("cashflow", ["购建固定资产"]),
    "dep_amort": ("cashflow", ["加:折旧及摊销"]),
    "cfo": ("cashflow", ["经营业务现金净额"]),
    "buybacks": ("cashflow", ["回购股份"]),
    "dividends_paid": ("cashflow", ["已付股息(融资)", "已付股息"]),
    "net_income": ("income", ["股东应占溢利"]),
    "tci": ("income", ["本公司拥有人应占全面收益总额"]),
}
# 有息负债 = 贷款 + 应付票据 + 应付债券 + 可转换票据及债券 + 租赁负债（流动＋非流动），与 A 股 `roic_inputs.DEBT_FIELDS` 同口径
HK_DEBT_KEYS = ("lt_loan", "st_loan", "notes_nc", "notes_c", "bonds", "convertibles", "lease_nc", "lease_c")
# 东财数据中心补缺源：美股利润表（报表币）、美股分红事件（每 ADR 美元）、港股分红事件（每股港币／人民币／美元）
EM_US_INCOME_ITEMS = {"net_income": "归属于母公司股东净利润", "tci": "本公司拥有人占全面收益总额"}
EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://emweb.securities.eastmoney.com/"}
HK_DPS_RE = re.compile(r"每股派(港币|人民币|美元)([\d.]+)元")
US_ADR_DPS_RE = re.compile(r"每1份ADR派([\d.]+)")
US_SHARE_DPS_RE = re.compile(r"每1股派([\d.]+)美元")
CCY_NAME = {"港币": "HKD", "人民币": "CNY", "美元": "USD"}


def load_fx() -> dict[str, float]:
    """`overseas_valuation_inputs.csv` 的汇率键（fx_usd_cny／fx_usd_hkd／fx_usd_twd／fx_usd_eur 等，均为 1 美元折多少目标币）。"""
    if not VALUATION_INPUTS.exists():
        return {}
    return {r["key"]: float(r["value"]) for r in csv.DictReader(VALUATION_INPUTS.open(encoding="utf-8")) if r["key"].startswith("fx_")}


def fx_convert(amount: float, ccy: str, target: str, fx: dict[str, float]) -> float | None:
    """ccy → target，经美元中转；缺汇率返回 None。"""
    if ccy == target:
        return amount
    per_usd = {"USD": 1.0}
    for key, val in fx.items():
        if key.startswith("fx_usd_"):
            per_usd[key[len("fx_usd_"):].upper()] = val
    if ccy not in per_usd or target not in per_usd:
        return None
    return amount / per_usd[ccy] * per_usd[target]


def em_datacenter(report: str, flt: str, cache: Path, refresh: bool, sort: str = "") -> list[dict]:
    """东财数据中心分页拉取（pageSize 500），落原始 JSON；下载失败沿用缓存。"""
    if cache.exists() and cache.stat().st_size > 2 and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    cached = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() and cache.stat().st_size > 2 else []
    allrows, page = [], 1
    while True:
        url = (f"{HK_API}?reportName={report}&columns=ALL&pageSize=500&pageNumber={page}{sort}&filter="
               + urllib.parse.quote(flt))
        try:
            d = json.loads(_get(url, EM_HEADERS, 30).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"  东财 {report} p{page}: 下载失败 {exc}")
            return cached
        res = d.get("result") or {}
        data = res.get("data") or []
        if not d.get("success") and "为空" not in str(d.get("message", "")):
            print(f"  东财 {report}: {d.get('message')}")
            return cached
        allrows += data
        if not data or page >= int(res.get("pages") or 1):
            break
        page += 1
        time.sleep(0.3)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(allrows, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.3)
    return allrows


def hk_dividend_events(code: str, refresh: bool) -> list[dict]:
    return em_datacenter("RPT_HKF10_INFO_DIVIDEND", f'(SECUCODE="{code}.HK")', RAW_DIR / "hk" / f"{code}_dividend.json",
                         refresh, "&sortColumns=NOTICE_DATE&sortTypes=-1")


def us_income_items(code: str, refresh: bool) -> list[dict]:
    rows: list[dict] = []
    for item in EM_US_INCOME_ITEMS.values():
        rows += em_datacenter("RPT_USF10_FN_INCOME", f'(SECURITY_CODE="{code}")(ITEM_NAME="{item}")',
                              RAW_DIR / "sec" / f"{code}_em_income_{item}.json", refresh, "&sortColumns=REPORT_DATE&sortTypes=-1")
    return rows


def us_dividend_events(code: str, refresh: bool) -> list[dict]:
    return em_datacenter("RPT_USF10_INFO_DIVIDEND", f'(SECURITY_CODE="{code}")', RAW_DIR / "sec" / f"{code}_em_dividend.json",
                         refresh, "&sortColumns=NOTICE_DATE&sortTypes=-1")


def dividends_from_events(events: list[dict], start: str, end: str, shares: float | None, target_ccy: str,
                          fx: dict[str, float], per_adr_shares: float = 1.0, market: str = "HK") -> float | None:
    """除净日落在 (start, end] 的现金分派合计（报表币，总额）。港股按「每股派 X 币」，美股按「每 1 份 ADR 派 X 美元」÷ 每 ADR 股数
    或「每 1 股派 X 美元」。
    无可解析事件返回 0；股数或汇率缺失返回 None。"""
    if not shares:
        return None
    total = 0.0
    for ev in events:
        ex = str(ev.get("EX_DIVIDEND_DATE") or "")[:10]
        if not ex or not (start < ex <= end):
            continue
        plan = str(ev.get("PLAN_EXPLAIN") or "")
        if market == "HK":
            m = HK_DPS_RE.search(plan)
            if not m:
                continue
            per_share, ccy = float(m.group(2)), CCY_NAME[m.group(1)]
        else:
            if str(ev.get("ASSIGN_TYPE") or "Cash") != "Cash":
                continue
            m = US_ADR_DPS_RE.search(plan)
            if m:
                per_share, ccy = float(m.group(1)) / per_adr_shares, "USD"       # 每 ADR 美元 ÷ 每 ADR 普通股数
            else:
                m = US_SHARE_DPS_RE.search(plan)
                if not m:
                    continue
                per_share, ccy = float(m.group(1)), "USD"                        # 本土发行人：每 1 股派 X 美元
        amount = fx_convert(per_share * shares, ccy, target_ccy, fx)
        if amount is None:
            return None
        total += amount
    return total


def fill_override_from_eastmoney(row: dict, annual: dict | None, income: list[dict], events: list[dict],
                                 shares_per_adr: float, fx: dict[str, float]) -> list[str]:
    """维护行缺归母净利／综合收益／年报后累计值时按东财补：年报行取 DATE_TYPE_CODE 001，TTM 行取本期累计（002／004／...）。返回补了哪些字段。"""
    filled: list[str] = []
    ccy = row["report_currency"]
    by_period: dict[tuple[str, str], dict[str, float]] = {}
    for it in income:
        if it.get("CURRENCY_ABBR") and it["CURRENCY_ABBR"] != ccy:
            continue
        by_period.setdefault((str(it["REPORT_DATE"])[:10], str(it["REPORT_TYPE"])), {})[it["ITEM_NAME"]] = _num(it.get("AMOUNT"))
    tags = dict(t.split("=", 1) for t in row["tags_used"].split(";") if "=" in t) if row.get("tags_used") else {}
    period = row["period"]
    if row["period_type"] == "annual":
        items = by_period.get((period, "年报"), {})
        for key, name in EM_US_INCOME_ITEMS.items():
            if row.get(key) is None and items.get(name) is not None:
                row[key], tags[key] = items[name], f"eastmoney:RPT_USF10_FN_INCOME:{name}"
                filled.append(key)
    else:
        items = by_period.get((period, "累计季报"), {})
        if row.get("net_income_ytd") is None and items.get(EM_US_INCOME_ITEMS["net_income"]) is not None:
            row["net_income_ytd"] = items[EM_US_INCOME_ITEMS["net_income"]]
            tags["net_income_ytd"] = "eastmoney:RPT_USF10_FN_INCOME:累计季报"
            filled.append("net_income_ytd")
        if row.get("dividends_paid_ytd") is None and annual:
            paid = dividends_from_events(events, annual["period"], period, _num(row.get("shares")), ccy, fx, shares_per_adr, "US")
            if paid is not None:
                row["dividends_paid_ytd"], tags["dividends_paid_ytd"] = paid, "eastmoney:RPT_USF10_INFO_DIVIDEND"
                filled.append("dividends_paid_ytd")
        if row.get("net_income") is None and annual and _num(annual.get("net_income")) is not None:
            prior = f"{int(period[:4]) - 1:04d}{period[4:]}"
            old = next((v.get(EM_US_INCOME_ITEMS["net_income"]) for (p, t), v in by_period.items()
                        if t == "累计季报" and abs((date.fromisoformat(p) - date.fromisoformat(prior)).days) <= 7), None)
            if old is not None and row.get("net_income_ytd") is not None:
                row["net_income"] = _num(annual["net_income"]) + row["net_income_ytd"] - old
                tags["net_income"] = "eastmoney:RPT_USF10_FN_INCOME:TTM"
                filled.append("net_income")
    row["tags_used"] = ";".join(f"{k}={v}" for k, v in sorted(tags.items()))
    return filled


def _num(v):
    try:
        return float(v) if v not in (None, "", "—") else None
    except (TypeError, ValueError):
        return None


def _load_csv_by(path: Path, keys: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    if not path.exists():
        return {}
    return {tuple(row.get(key, "") for key in keys): row
            for row in csv.DictReader(path.open(encoding="utf-8-sig"))}


def load_report_evidence(as_of: str) -> dict[str, dict[str, str]]:
    rows = _load_csv_by(REPORT_EVIDENCE, ("security_code",))
    return {key[0]: row for key, row in rows.items() if row.get("evidence_date", "") <= as_of}


def load_statement_overrides(as_of: str) -> list[dict]:
    if not STATEMENT_OVERRIDES.exists():
        return []
    rows = []
    for raw in csv.DictReader(STATEMENT_OVERRIDES.open(encoding="utf-8-sig")):
        if raw.get("notice_date", "") > as_of:
            continue
        rows.append(_build_row(
            raw["market"], raw["security_code"], raw["security_name"], raw["period"], raw["notice_date"],
            raw["report_currency"], *[_num(raw.get(key)) for key in
                                      ("revenue", "operating_income", "pretax", "income_tax", "interest_expense",
                                       "total_equity", "parent_equity", "minority_equity", "interest_debt", "cash_like",
                                       "capex", "dep_amort", "cfo", "shares")],
            {}, raw.get("source") or "official statement override",
            TAX_DEFAULT.get(raw["market"], 0.25),
            buybacks=_num(raw.get("buybacks")) or 0.0,
            dividends=_num(raw.get("dividends_paid")) or 0.0,
            net_income=_num(raw.get("net_income")), tci=_num(raw.get("tci")),
            net_income_ytd=_num(raw.get("net_income_ytd")), dividends_ytd=_num(raw.get("dividends_paid_ytd")),
            period_type=raw.get("period_type") or "ttm",
            report_label=raw.get("report_label") or "",
            evidence_url=raw.get("evidence_url") or "",
        ))
    return rows


def apply_evidence(rows: list[dict], evidence: dict[str, dict[str, str]]) -> list[dict]:
    """Attach only a matching, already-public report event to a statement row."""
    for row in rows:
        item = evidence.get(row["security_code"])
        if not item or item.get("report_period") != row.get("period"):
            continue
        row["notice_date"] = item["evidence_date"]
        row["report_label"] = item["report_event"]
        row["evidence_url"] = item.get("evidence_url", "")
    return rows


def _get(url: str, headers: dict, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            data = gzip.decompress(data)
        return data


# ------------------------------------------------------------------ SEC
def sec_download(symbol: str, cik: str, refresh: bool) -> dict | None:
    out = RAW_DIR / "sec" / f"{symbol}.json"
    if out.exists() and out.stat().st_size > 1000 and not refresh:
        return json.loads(out.read_text(encoding="utf-8"))
    try:
        data = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                    {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    except Exception as exc:  # noqa: BLE001
        print(f"  SEC {symbol}: 下载失败 {exc}")
        # 刷新失败不得把一只原本可估值的公司变成空；保留最近一次成功快照。
        return json.loads(out.read_text(encoding="utf-8")) if out.exists() and out.stat().st_size > 1000 else None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    time.sleep(0.4)
    return json.loads(data.decode("utf-8"))


def _sec_series(tax: dict, concepts: list[str], duration: bool) -> tuple[dict[str, float], str, str]:
    """{期末: 值}（各候选标签按优先级合并）、所用标签、单位。"""
    merged: dict[str, tuple[str, float]] = {}
    used, unit_used = [], ""
    for concept in concepts:
        node = tax.get(concept)
        if not node:
            continue
        units = node.get("units", {})
        unit = next((u for u in units if u not in ("pure",)), None)
        if unit is None:
            continue
        for e in units[unit]:
            if e.get("fp") != "FY" or not str(e.get("form", "")).startswith(("10-K", "20-F", "40-F")):
                continue
            end = e.get("end")
            if not end:
                continue
            if duration:
                start = e.get("start")
                if not start:
                    continue
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                if not 300 <= days <= 380:
                    continue
            filed = e.get("filed", "")
            if end not in merged or (merged[end][0] < filed and concept == used[0] if used else True):
                # 同一期末取最新申报；不同标签之间按候选顺序，先到者优先（只补缺）
                if end in merged and concept not in used[:1]:
                    continue
                merged[end] = (filed, float(e["val"]), "")
        if node and concept not in used:
            used.append(concept)
            unit_used = unit_used or unit
    if not duration:
        # 换签期的年末时点值：发行人在 10-K 只打新签之外的总额签、新签只出现在后续 10-Q 的比较期时，
        # 同一资产负债表日从 10-Q 比较期按候选顺序补缺（只补 10-K 未给出的期末，取最新申报）。
        for concept in concepts:
            node = tax.get(concept)
            if not node:
                continue
            units = node.get("units", {})
            unit = next((u for u in units if u not in ("pure",)), None)
            if unit is None:
                continue
            for e in units[unit]:
                end, filed = e.get("end"), str(e.get("filed") or "")
                if not end or e.get("start") or not str(e.get("form", "")).startswith("10-Q"):
                    continue
                if end in merged and (merged[end][0] >= filed or merged[end][2] != concept):
                    continue
                merged[end] = (filed, float(e["val"]), concept)
            if concept not in used:
                used.append(concept)
                unit_used = unit_used or unit
    return {k: v[1] for k, v in merged.items()}, "+".join(used), unit_used


def _sec_entries(tax: dict, concepts: list[str]) -> tuple[list[dict], str]:
    """Return the freshest usable concept; concept order breaks equal-date ties."""
    found = []
    for rank, concept in enumerate(concepts):
        node = tax.get(concept) or {}
        candidates = [(len(entries), entries) for unit, entries in node.get("units", {}).items()
                      if unit != "pure" and entries]
        if candidates:
            entries = max(candidates, key=lambda item: item[0])[1]
            freshest = max((str(e.get("filed") or "") for e in entries), default="")
            found.append((freshest, -rank, entries, concept))
    if not found:
        return [], ""
    _, _, entries, concept = max(found, key=lambda item: (item[0], item[1]))
    return entries, concept


def _days(entry: dict) -> int | None:
    try:
        return (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
    except (KeyError, TypeError, ValueError):
        return None


def _annual_notice(tax: dict, end: str) -> str:
    filings = []
    for node in tax.values():
        for entries in node.get("units", {}).values():
            filings += [str(e.get("filed") or "") for e in entries
                        if e.get("end") == end and e.get("fp") == "FY"
                        and str(e.get("form", "")).startswith(("10-K", "20-F", "40-F"))
                        and e.get("filed")]
    return min(filings) if filings else end


def _latest_10q_identity(tax: dict, concepts: list[str]) -> tuple[str, str, str] | None:
    entries, _ = _sec_entries(tax, concepts)
    valid = [e for e in entries if e.get("form") == "10-Q" and e.get("fp") in {"Q1", "Q2", "Q3"}
             and e.get("filed") and e.get("end") and (_days(e) or 0) >= 60]
    if not valid:
        return None
    filed = max(str(e["filed"]) for e in valid)
    current = max((e for e in valid if e.get("filed") == filed), key=lambda e: str(e["end"]))
    return str(current["end"]), str(current["fp"]), filed


def _duration_pair(tax: dict, concepts: list[str], end: str, filed: str) -> tuple[float | None, float | None, str]:
    entries, concept = _sec_entries(tax, concepts)
    current = [e for e in entries if e.get("form") == "10-Q" and e.get("end") == end
               and e.get("filed") == filed and 60 <= (_days(e) or 0) <= 300]
    if not current:
        return None, None, concept
    cur = max(current, key=lambda e: _days(e) or 0)
    duration = _days(cur) or 0
    prior = [e for e in entries if e.get("form") == "10-Q" and e.get("filed") == filed
             and e.get("end") < end and abs((_days(e) or -999) - duration) <= 7]
    if not prior:
        prior = [e for e in entries if e.get("form") == "10-Q" and e.get("end") < end
                 and abs((_days(e) or -999) - duration) <= 7]
    old = max(prior, key=lambda e: (str(e.get("end") or ""), str(e.get("filed") or "")), default=None)
    return float(cur["val"]), (float(old["val"]) if old else None), concept


def _instant_value(tax: dict, concepts: list[str], end: str, filed: str) -> tuple[float | None, str]:
    """期末时点值：先取最新申报的标签；该标签在 `end` 无值时按候选顺序逐个补缺（发行人换签时旧签只到上一期）。"""
    entries, concept = _sec_entries(tax, concepts)
    ordered = [(entries, concept)] + [(_sec_entries(tax, [c])[0], c) for c in concepts if c != concept]
    for cand_entries, cand_concept in ordered:
        exact = [e for e in cand_entries if e.get("end") == end and not e.get("start")
                 and str(e.get("filed") or "") <= filed]
        if not exact:
            exact = [e for e in cand_entries if e.get("end") == end and str(e.get("filed") or "") <= filed]
        hit = max(exact, key=lambda e: str(e.get("filed") or ""), default=None)
        if hit is not None:
            return float(hit["val"]), cand_concept
    return None, concept


def _shares_value(tax: dict, concepts: list[str], end: str, filed: str) -> tuple[float | None, str]:
    entries, concept = _sec_entries(tax, concepts)
    exact = [e for e in entries if e.get("form") == "10-Q" and e.get("end") == end
             and e.get("filed") == filed and 60 <= (_days(e) or 0) <= 300]
    hit = min(exact, key=lambda e: _days(e) or 9999, default=None)
    return (float(hit["val"]) if hit else None), concept


def _ytd_dividends(current: float | None, annual_paid: float | None) -> float | None:
    """年报期末之后的已付股息：季报现金流量表有该行取其值；无该行时，上一财年未付股息的公司记 0，
    付过股息的公司记缺（None，估值侧 x 不可验证即不调整）。"""
    if current is not None:
        return abs(current)
    return 0.0 if not annual_paid else None


def sec_current_extract(symbol: str, name: str, tax: dict, maps: dict, annuals: list[dict],
                        evidence_date: str = "") -> dict | None:
    """Build a latest TTM snapshot from a domestic issuer's latest 10-Q."""
    identity = _latest_10q_identity(tax, maps["revenue"])
    if not identity or not annuals:
        return None
    end, fp, filed = identity
    annual = annuals[-1]
    if end <= annual["period"]:
        return None
    tags: dict[str, str] = {}

    def ttm(key: str) -> float | None:
        cur, old, concept = _duration_pair(tax, maps[key], end, filed)
        tags[key] = concept
        base = _num(annual.get(key))
        return base + cur - old if base is not None and cur is not None and old is not None else None

    def inst(key: str) -> float | None:
        value, concept = _instant_value(tax, maps[key], end, filed)
        tags[key] = concept
        return value

    def ytd(key: str) -> float | None:
        cur, _old, _concept = _duration_pair(tax, maps[key], end, filed)
        return cur

    revenue, opinc, pretax, taxv = ttm("revenue"), ttm("operating_income"), ttm("pretax"), ttm("income_tax")
    interest = ttm("interest_expense") or 0.0
    total_eq, parent_eq, minority = inst("total_equity"), inst("parent_equity"), inst("minority_equity") or 0.0
    if total_eq is not None and parent_eq is not None and abs(total_eq - parent_eq) < 1e-6 and minority:
        total_eq = parent_eq + minority
    lt_nc, lt_cur, lt_total = inst("lt_debt_noncurrent"), inst("lt_debt_current"), inst("lt_debt_total")
    debt = ((lt_nc or 0.0) + (lt_cur or 0.0)) if lt_nc is not None else (lt_total or 0.0)
    debt += inst("st_debt") or 0.0
    cash = (inst("cash") or 0.0) + (inst("cash_invest") or 0.0)
    shares, share_tag = _shares_value(tax, maps["shares"], end, filed)
    tags["shares"] = share_tag
    if revenue is None or (pretax is None and opinc is None) or parent_eq is None or shares is None:
        return None
    fy = int(annual["period"][:4]) + 1
    label = {"Q1": "一季报", "Q2": "二季报", "Q3": "三季报"}[fp]
    return _build_row("US", symbol, name, end, evidence_date or filed, annual["report_currency"], revenue,
                      opinc, pretax, taxv, interest, total_eq, parent_eq, minority, debt, cash,
                      abs(ttm("capex") or 0.0), ttm("dep_amort") or 0.0, ttm("cfo"), shares, tags,
                      "SEC companyfacts 10-Q TTM", TAX_DEFAULT["US"],
                      buybacks=abs(ttm("buybacks") or 0.0), dividends=abs(ttm("dividends_paid") or 0.0),
                      net_income=ttm("net_income"), tci=ttm("tci"), net_income_ytd=ytd("net_income"),
                      dividends_ytd=_ytd_dividends(ytd("dividends_paid"), _num(annual.get("dividends_paid"))),
                      period_type="ttm", report_label=f"{label}（FY{fy} {fp}，截至 {end}）")


def sec_extract(symbol: str, name: str, data: dict) -> list[dict]:
    facts = data.get("facts", {})
    if "ifrs-full" in facts and "ProfitLossBeforeTax" in facts["ifrs-full"]:
        tax, maps = facts["ifrs-full"], IFRS
        src = "SEC companyfacts ifrs-full"
    else:
        tax, maps = facts.get("us-gaap", {}), GAAP
        src = "SEC companyfacts us-gaap"
    series: dict[str, dict[str, float]] = {}
    tags: dict[str, str] = {}
    ccy = ""
    for key, concepts in maps.items():
        s, used, unit = _sec_series(tax, concepts, key in DURATION)
        series[key] = s
        if used:
            tags[key] = used
        if key == "revenue" and unit:
            ccy = unit
    ends = sorted(set(series["revenue"]) | set(series["pretax"]) | set(series["operating_income"]))
    rows = []
    # 财年公开可得日取该期 10-K／20-F／40-F 的实际 filed 日。
    for end in ends:
        def v(key):
            return series.get(key, {}).get(end)
        rev, pretax, opinc, taxv = v("revenue"), v("pretax"), v("operating_income"), v("income_tax")
        if rev is None and pretax is None:
            continue
        intexp = v("interest_expense") or 0.0
        # 有息负债：长期（非流动+一年内到期，缺拆分则取合计）+ 短期
        if v("lt_debt_noncurrent") is not None:
            lt = (v("lt_debt_noncurrent") or 0.0) + (v("lt_debt_current") or 0.0)
        else:
            lt = v("lt_debt_total") or 0.0
        st = v("st_debt") or 0.0
        debt = lt + st
        cash = (v("cash") or 0.0) + (v("cash_invest") or 0.0)
        total_eq, parent_eq, minority = v("total_equity"), v("parent_equity"), v("minority_equity") or 0.0
        if total_eq is not None and parent_eq is not None and abs(total_eq - parent_eq) < 1e-6 and minority:
            total_eq = parent_eq + minority
        shares = v("shares") or v("shares_instant")
        rows.append(_build_row("US", symbol, name, end, _annual_notice(tax, end), ccy or "USD", rev, opinc, pretax, taxv, intexp,
                               total_eq, parent_eq, minority, debt, cash, v("capex") or 0.0, v("dep_amort") or 0.0,
                               v("cfo"), shares, tags, src, TAX_DEFAULT["US"],
                               buybacks=abs(v("buybacks") or 0.0), dividends=abs(v("dividends_paid") or 0.0),
                               net_income=v("net_income"), tci=v("tci"),
                               period_type="annual", report_label=f"年报（FY{end[:4]}，截至 {end}）"))
    return rows


# ------------------------------------------------------------------ HK
def hk_download(code: str, refresh: bool) -> dict[str, list[dict]]:
    out_all = {}
    for kind, rn in (("balance", "RPT_HKF10_FN_BALANCE_PC"), ("income", "RPT_HKF10_FN_INCOME_PC"), ("cashflow", "RPT_HKF10_FN_CASHFLOW_PC")):
        out = RAW_DIR / "hk" / f"{code}_{kind}.json"
        if out.exists() and not refresh:
            out_all[kind] = json.loads(out.read_text(encoding="utf-8"))
            continue
        cached = json.loads(out.read_text(encoding="utf-8")) if out.exists() and out.stat().st_size > 1000 else []
        allrows, page, complete = [], 1, True
        while True:
            url = (f"{HK_API}?reportName={rn}&columns=ALL&pageSize=500&pageNumber={page}&sortColumns=REPORT_DATE&sortTypes=-1&filter="
                   + urllib.parse.quote(f'(SECUCODE="{code}.HK")'))
            try:
                d = json.loads(_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://emweb.securities.eastmoney.com/"}, 30).decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"  HK {code} {kind} p{page}: 下载失败 {exc}")
                complete = False
                break
            res = d.get("result") or {}
            data = res.get("data") or []
            allrows += data
            if not data or page >= int(res.get("pages") or 1):
                break
            page += 1
            time.sleep(0.3)
        if complete and allrows:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(allrows, ensure_ascii=False), encoding="utf-8")
            out_all[kind] = allrows
        else:
            out_all[kind] = cached
        time.sleep(0.3)
    return out_all


def hk_extract(code: str, name: str, tables: dict[str, list[dict]], shares: float | None,
               events: list[dict] | None = None, fx: dict[str, float] | None = None) -> list[dict]:
    def table_map(kind: str) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for r in tables.get(kind, []):
            if str(r.get("DATE_TYPE_CODE")) != "001":
                continue
            period = str(r.get("REPORT_DATE", ""))[:10]
            amt = _num(r.get("AMOUNT"))
            if amt is None:
                continue
            out.setdefault(period, {})[r.get("STD_ITEM_NAME", "")] = amt
        return out
    maps = {k: table_map(k) for k in ("balance", "income", "cashflow")}
    periods = sorted(set(maps["income"]) | set(maps["balance"]))
    rows, tags = [], {}
    def pick(period, key):
        kind, names = HK_ITEMS[key]
        for n in names:
            if n in maps[kind].get(period, {}):
                tags[key] = f"{kind}:{n}"
                return maps[kind][period][n]
        return None
    prev_period = ""
    for period in periods:
        rev, pretax, opinc, taxv = pick(period, "revenue"), pick(period, "pretax"), pick(period, "operating_income"), pick(period, "income_tax")
        if rev is None and pretax is None:
            continue
        intexp = pick(period, "interest_expense") or 0.0
        debt = sum(pick(period, k) or 0.0 for k in HK_DEBT_KEYS)
        cash = (pick(period, "cash") or 0.0) + (pick(period, "deposits") or 0.0)
        dividends = pick(period, "dividends_paid")
        if dividends is None and events and prev_period:
            # 现金流量表无「已付股息」行：按分红事件（除净日落在上一财年末与本期末之间）× 最新已发行股数折报表币
            dividends = dividends_from_events(events, prev_period, period, shares, HK_REPORT_CCY.get(code, "CNY"), fx or {})
            if dividends is not None:
                tags["dividends_paid"] = "eastmoney:RPT_HKF10_INFO_DIVIDEND"
        prev_period = period
        rows.append(_build_row("HK", code, name, period, period, HK_REPORT_CCY.get(code, "CNY"), rev, opinc, pretax,
                               None if taxv is None else abs(taxv), intexp, pick(period, "total_equity"), pick(period, "parent_equity"),
                               pick(period, "minority_equity") or 0.0, debt, cash, abs(pick(period, "capex") or 0.0),
                               pick(period, "dep_amort") or 0.0, pick(period, "cfo"), shares, tags,
                               "eastmoney HK F10 (RPT_HKF10_FN_*_PC, DATE_TYPE_CODE=001)", TAX_DEFAULT["HK"],
                               buybacks=abs(pick(period, "buybacks") or 0.0), dividends=abs(dividends or 0.0),
                               net_income=pick(period, "net_income"), tci=pick(period, "tci"),
                               period_type="annual", report_label=f"年报（FY{period[:4]}，截至 {period}）"))
    return rows


def hk_current_extract(code: str, name: str, tables: dict[str, list[dict]], shares: float | None,
                       annuals: list[dict], evidence_date: str = "", events: list[dict] | None = None,
                       fx: dict[str, float] | None = None) -> dict | None:
    """Build the latest verified HK quarterly/interim TTM snapshot from F10 cumulative statements."""
    if not annuals or not evidence_date:
        return None

    maps: dict[str, dict[str, dict[str, float]]] = {}
    for kind in ("balance", "income", "cashflow"):
        by_period: dict[str, dict[str, float]] = {}
        for row in tables.get(kind, []):
            period = str(row.get("REPORT_DATE", ""))[:10]
            amount = _num(row.get("AMOUNT"))
            if period and amount is not None:
                by_period.setdefault(period, {})[str(row.get("STD_ITEM_NAME", ""))] = amount
        maps[kind] = by_period

    annual = annuals[-1]
    candidates = sorted(p for p in (set(maps["income"]) | set(maps["balance"])) if p > annual["period"])
    if not candidates:
        annual["notice_date"] = evidence_date
        return None
    period = candidates[-1]
    previous = f"{int(period[:4]) - 1:04d}{period[4:]}"
    tags: dict[str, str] = {}

    def pick(which: str, key: str) -> float | None:
        kind, names = HK_ITEMS[key]
        selected = {"current": period, "previous": previous, "annual": annual["period"]}[which]
        for item in names:
            if item in maps[kind].get(selected, {}):
                tags[key] = f"{kind}:{item}"
                return maps[kind][selected][item]
        return None

    annual_values = {key: _num(annual.get(key)) for key in
                     ("revenue", "operating_income", "pretax", "income_tax", "interest_expense",
                      "capex", "dep_amort", "cfo", "buybacks", "dividends_paid", "net_income", "tci")}

    def ttm(key: str) -> float | None:
        cur, old, base = pick("current", key), pick("previous", key), annual_values[key]
        if key in {"income_tax", "interest_expense", "capex", "buybacks", "dividends_paid"}:
            cur = abs(cur) if cur is not None else None
            old = abs(old) if old is not None else None
            base = abs(base) if base is not None else None
        return base + cur - old if base is not None and cur is not None and old is not None else None

    revenue, opinc, pretax = ttm("revenue"), ttm("operating_income"), ttm("pretax")
    taxv = ttm("income_tax")
    interest = ttm("interest_expense") or 0.0
    total_eq, parent_eq = pick("current", "total_equity"), pick("current", "parent_equity")
    minority = pick("current", "minority_equity") or 0.0
    debt = sum(pick("current", key) or 0.0 for key in HK_DEBT_KEYS)
    cash = (pick("current", "cash") or 0.0) + (pick("current", "deposits") or 0.0)
    if revenue is None or (pretax is None and opinc is None) or parent_eq is None or not shares:
        return None
    dividends_ytd = _ytd_dividends(pick("current", "dividends_paid"), annual_values["dividends_paid"])
    if dividends_ytd is None and events:
        dividends_ytd = dividends_from_events(events, annual["period"], period, shares, HK_REPORT_CCY.get(code, "CNY"), fx or {})
        if dividends_ytd is not None:
            tags["dividends_paid_ytd"] = "eastmoney:RPT_HKF10_INFO_DIVIDEND"
    annual_date, current_date = date.fromisoformat(annual["period"]), date.fromisoformat(period)
    quarter = ((current_date.year - annual_date.year) * 12 + current_date.month - annual_date.month) // 3
    label = {1: "一季报", 2: "中报", 3: "三季报"}.get(quarter, "定期报告")
    fiscal_year = int(annual["period"][:4]) + (1 if period > annual["period"] else 0)
    return _build_row("HK", code, name, period, evidence_date, HK_REPORT_CCY.get(code, "CNY"), revenue,
                      opinc, pretax, abs(taxv) if taxv is not None else None, abs(interest), total_eq, parent_eq,
                      minority, debt, cash, abs(ttm("capex") or 0.0), ttm("dep_amort") or 0.0, ttm("cfo"), shares,
                      tags, "eastmoney HK F10 TTM", TAX_DEFAULT["HK"],
                      buybacks=abs(ttm("buybacks") or 0.0), dividends=abs(ttm("dividends_paid") or 0.0),
                      net_income=ttm("net_income"), tci=ttm("tci"), net_income_ytd=pick("current", "net_income"),
                      dividends_ytd=dividends_ytd,
                      period_type="ttm", report_label=f"{label}（FY{fiscal_year}，截至 {period}）")


def _build_row(market, code, name, period, notice, ccy, rev, opinc, pretax, taxv, intexp, total_eq, parent_eq, minority,
               debt, cash, capex, dep, cfo, shares, tags, src, tax_default, buybacks=0.0, dividends=0.0,
               net_income=None, tci=None, net_income_ytd=None, dividends_ytd=None,
               period_type="annual", report_label="", evidence_url="") -> dict:
    # 与 roic_inputs.load_statements 同式
    ebit = (pretax + intexp) if pretax is not None else opinc
    if pretax is not None and pretax > 0 and taxv is not None:
        lo, hi = roic_inputs.TAX_RATE_BOUNDS
        rate, observed = min(max(taxv / pretax, lo), hi), True
    else:
        rate, observed = tax_default, False
    nopat = ebit * (1 - rate) if ebit is not None else None
    excess = max(0.0, cash - roic_inputs.OPERATING_CASH_RATIO * (rev or 0.0))
    ic = (debt + total_eq - excess) if total_eq is not None else None
    return {
        "market": market, "security_code": code, "security_name": name, "period": period,
        "fiscal_year": period[:4], "notice_date": notice, "report_currency": ccy,
        "revenue": rev, "operating_income": opinc, "pretax": pretax, "income_tax": taxv, "interest_expense": intexp,
        "ebit": ebit, "tax_rate": round(rate, 6), "tax_rate_observed": int(observed), "nopat": nopat,
        "total_equity": total_eq, "parent_equity": parent_eq, "minority_equity": minority,
        "interest_debt": debt, "cash_like": cash, "excess_cash": excess,
        "invested_capital": ic if (ic is not None and ic > 0) else None,
        "capex": capex, "dep_amort": dep, "cfo": cfo, "shares": shares,
        "buybacks": buybacks, "dividends_paid": dividends,
        "net_income": net_income, "tci": tci, "net_income_ytd": net_income_ytd, "dividends_paid_ytd": dividends_ytd,
        "tags_used": ";".join(f"{k}={v}" for k, v in sorted(tags.items())), "source": src,
        "period_type": period_type, "report_label": report_label, "evidence_url": evidence_url,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--refresh", action="store_true", help="强制重新下载原始 JSON")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    watch = list(csv.DictReader(WATCHLIST.open(encoding="utf-8-sig")))
    cik = {r["symbol"]: r["sec_cik"].zfill(10) for r in csv.DictReader(US_INDICATORS.open(encoding="utf-8-sig")) if r.get("sec_cik")}
    hk_shares = {r["security_code"]: _num(r.get("issued_shares")) for r in csv.DictReader(HK_INDICATORS.open(encoding="utf-8-sig"))}
    evidence = load_report_evidence(args.as_of)
    overrides = load_statement_overrides(args.as_of)
    override_keys = {(r["security_code"], r["period"], r["period_type"]) for r in overrides}
    fx = load_fx()
    try:
        from build_overseas_roic_bands import COMPANY_CFG  # 每 ADR 普通股数（美股分红事件折每股用）
    except Exception:  # noqa: BLE001
        COMPANY_CFG = {}
    fills: list[str] = []
    rows: list[dict] = []
    summary = []
    for r in watch:
        market, code, name = r["market_type"].upper(), r["security_code"], r["security_name"]
        item = evidence.get(code) or {}
        if market == "US":
            c = cik.get(code)
            if not c:
                summary.append(f"{market} {code} {name}: 无 CIK（未上市/无申报），不出行"); continue
            data = sec_download(code, c, args.refresh)
            if not data:
                summary.append(f"{market} {code} {name}: SEC 无数据"); continue
            got = sec_extract(code, name, data)
            facts = data.get("facts", {})
            if "ifrs-full" in facts and "ProfitLossBeforeTax" in facts["ifrs-full"]:
                tax, maps = facts["ifrs-full"], IFRS
            else:
                tax, maps = facts.get("us-gaap", {}), GAAP
            current = sec_current_extract(code, name, tax, maps, got, item.get("evidence_date", ""))
            if current and current["period"] == item.get("report_period"):
                got.append(current)
        elif market == "HK":
            tables = hk_download(code, args.refresh)
            events = hk_dividend_events(code, args.refresh)
            got = hk_extract(code, name, tables, hk_shares.get(code), events, fx)
            current = hk_current_extract(code, name, tables, hk_shares.get(code), got, item.get("evidence_date", ""), events, fx)
            if current and current["period"] == item.get("report_period"):
                got.append(current)
        else:
            summary.append(f"{market} {code} {name}: 该市场无三表取数源，不出行（清单保持无法估值）"); continue
        # 官方报表维护行优先于自动提取；SEC companyfacts 对 6-K 境外发行人季报通常没有结构化事实。
        got = [g for g in got if (code, g["period"], g["period_type"]) not in override_keys]
        own_overrides = [g for g in overrides if g["security_code"] == code]
        if own_overrides and market == "US" and any(g.get(k) is None for g in own_overrides
                                                    for k in ("net_income", "tci", "net_income_ytd", "dividends_paid_ytd")):
            income, events = us_income_items(code, args.refresh), us_dividend_events(code, args.refresh)
            adr = float(COMPANY_CFG.get(code, {}).get("adr", 1) or 1)
            for g in own_overrides:
                annual_ref = max((a for a in got + own_overrides if a["period_type"] == "annual" and a["period"] < g["period"]),
                                 key=lambda a: a["period"], default=None) if g["period_type"] == "ttm" else None
                done = fill_override_from_eastmoney(g, annual_ref, income, events, adr, fx)
                if done:
                    fills.append(f"{code} {g['period']} {g['period_type']}: 东财补 {'/'.join(done)}")
        got += own_overrides
        got = apply_evidence(got, evidence)
        got.sort(key=lambda g: (g["period"], 0 if g["period_type"] == "annual" else 1))
        rows += got
        annuals = [g for g in got if g.get("period_type") == "annual"]
        current = [g for g in got if g.get("period_type") == "ttm"]
        latest = current[-1] if current else (annuals[-1] if annuals else None)
        summary.append(f"{market} {code} {name}: {len(annuals)} 个财年"
                       f"{'＋TTM ' + current[-1]['period'] if current else ''}，"
                       f"证据 {latest['notice_date'] if latest else '—'} {latest['report_label'] if latest else '—'}，"
                       f"币种 {latest['report_currency'] if latest else '—'}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in FIELDS})
    print("\n".join(summary))
    if fills:
        print("维护行补缺：" + "；".join(fills))
    print(f"wrote {len(rows)} rows → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

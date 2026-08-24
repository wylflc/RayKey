#!/usr/bin/env python3
"""海外关注清单（§6.8）的三大报表取数 → ROIC 口径逐年输入（与 A 股 `roic_inputs.RoicYear` 同字段）。

来源（2026-08-23 起，用户指令「海外公司同样应用当前估值方法」）：
* 美股／美元 ADR：SEC XBRL companyfacts（`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`），按 CIK
  取全部已申报事实，只留 `fp=FY` 且表单为 10-K/20-F/40-F 的年度值；持续期科目要求 300~380 天，
  同一期末取**最新申报**（含重述）。US-GAAP 与 IFRS（20-F，如台积电）两套标签都映射。
* 港股：东财 HK F10 三张表（`RPT_HKF10_FN_{BALANCE,INCOME,CASHFLOW}_PC`），`DATE_TYPE_CODE=001` 为财年。
  报表货币按公司（清单 6 家均为人民币）。股数取 `hong_kong_financial_indicators.csv` 最新已发行股数。
* 韩股：无免密钥三表源——不出行，清单上保持「无法估值」并写明缺口（§6.5.2.4）。
原始 JSON 落 `data/raw/overseas_statements/`（不入库，≈4 MB/家）；提取结果落 `data/interim/overseas_roic_years.csv`（入库）。

字段口径与 `roic_inputs.load_statements` 逐项对齐：
  ebit = 除税前溢利 + 利息费用；tax_rate = 所得税/除税前溢利（利润非正回退市场法定税率，夹 [0,40%]）；
  nopat = ebit×(1−t)；excess_cash = max(0, 现金类 − 2%×营收)；invested_capital = 有息负债 + 总权益 − 超额现金。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs  # noqa: E402

WATCHLIST = ROOT / "data/processed/overseas_watchlist_valuation.csv"
US_INDICATORS = ROOT / "data/interim/us_financial_indicators.csv"
HK_INDICATORS = ROOT / "data/interim/hong_kong_financial_indicators.csv"
RAW_DIR = ROOT / "data/raw/overseas_statements"
OUT = ROOT / "data/interim/overseas_roic_years.csv"
UA = "RayKey-AShareQuant research bot (personal research use)"
HK_API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
# 港股清单的报表货币（东财 HK F10 不带币种列；6 家均以人民币列报）
HK_REPORT_CCY = {"00700": "CNY", "09992": "CNY", "09618": "CNY", "09988": "CNY", "03690": "CNY", "06862": "CNY"}
TAX_DEFAULT = {"US": 0.21, "HK": 0.165}

FIELDS = ["market", "security_code", "security_name", "period", "fiscal_year", "notice_date", "report_currency",
          "revenue", "operating_income", "pretax", "income_tax", "interest_expense", "ebit", "tax_rate", "tax_rate_observed",
          "nopat", "total_equity", "parent_equity", "minority_equity", "interest_debt", "cash_like", "excess_cash",
          "invested_capital", "capex", "dep_amort", "cfo", "shares", "buybacks", "dividends_paid", "tags_used", "source"]

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
    "cash_invest": ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dep_amort": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                  "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "shares": ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
    "shares_instant": ["CommonStockSharesOutstanding"],
    # OI-082：回购与分红现金流（回购用于权益回加，分红只作展示）
    "buybacks": ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "PaymentsOfOrdinaryDividends"],
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
}
DURATION = {"revenue", "operating_income", "pretax", "income_tax", "interest_expense", "capex", "dep_amort", "cfo", "shares", "buybacks", "dividends_paid"}
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
    "cash": ("balance", ["现金及等价物"]),
    "deposits": ("balance", ["短期存款"]),
    "capex": ("cashflow", ["购建固定资产"]),
    "dep_amort": ("cashflow", ["加:折旧及摊销"]),
    "cfo": ("cashflow", ["经营业务现金净额"]),
    "buybacks": ("cashflow", ["回购股份"]),
    "dividends_paid": ("cashflow", ["已付股息(融资)", "已付股息"]),
}


def _num(v):
    try:
        return float(v) if v not in (None, "", "—") else None
    except (TypeError, ValueError):
        return None


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
        return None
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
                merged[end] = (filed, float(e["val"]))
        if node and concept not in used:
            used.append(concept)
            unit_used = unit_used or unit
    return {k: v[1] for k, v in merged.items()}, "+".join(used), unit_used


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
    # 期末→财年申报日（取该期末任一持续期科目的最早 filed 不可得，统一用期末+90 天近似；只用于排序/可得日）
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
        rows.append(_build_row("US", symbol, name, end, end, ccy or "USD", rev, opinc, pretax, taxv, intexp,
                               total_eq, parent_eq, minority, debt, cash, v("capex") or 0.0, v("dep_amort") or 0.0,
                               v("cfo"), shares, tags, src, TAX_DEFAULT["US"],
                               buybacks=abs(v("buybacks") or 0.0), dividends=abs(v("dividends_paid") or 0.0)))
    return rows


# ------------------------------------------------------------------ HK
def hk_download(code: str, refresh: bool) -> dict[str, list[dict]]:
    out_all = {}
    for kind, rn in (("balance", "RPT_HKF10_FN_BALANCE_PC"), ("income", "RPT_HKF10_FN_INCOME_PC"), ("cashflow", "RPT_HKF10_FN_CASHFLOW_PC")):
        out = RAW_DIR / "hk" / f"{code}_{kind}.json"
        if out.exists() and not refresh:
            out_all[kind] = json.loads(out.read_text(encoding="utf-8"))
            continue
        allrows, page = [], 1
        while True:
            url = (f"{HK_API}?reportName={rn}&columns=ALL&pageSize=500&pageNumber={page}&sortColumns=REPORT_DATE&sortTypes=-1&filter="
                   + urllib.parse.quote(f'(SECUCODE="{code}.HK")'))
            try:
                d = json.loads(_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://emweb.securities.eastmoney.com/"}, 30).decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"  HK {code} {kind} p{page}: 下载失败 {exc}")
                break
            res = d.get("result") or {}
            data = res.get("data") or []
            allrows += data
            if not data or page >= int(res.get("pages") or 1):
                break
            page += 1
            time.sleep(0.3)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(allrows, ensure_ascii=False), encoding="utf-8")
        out_all[kind] = allrows
        time.sleep(0.3)
    return out_all


def hk_extract(code: str, name: str, tables: dict[str, list[dict]], shares: float | None) -> list[dict]:
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
    for period in periods:
        rev, pretax, opinc, taxv = pick(period, "revenue"), pick(period, "pretax"), pick(period, "operating_income"), pick(period, "income_tax")
        if rev is None and pretax is None:
            continue
        intexp = pick(period, "interest_expense") or 0.0
        debt = sum(pick(period, k) or 0.0 for k in ("lt_loan", "st_loan", "notes_nc", "notes_c"))
        cash = (pick(period, "cash") or 0.0) + (pick(period, "deposits") or 0.0)
        rows.append(_build_row("HK", code, name, period, period, HK_REPORT_CCY.get(code, "CNY"), rev, opinc, pretax,
                               None if taxv is None else abs(taxv), intexp, pick(period, "total_equity"), pick(period, "parent_equity"),
                               pick(period, "minority_equity") or 0.0, debt, cash, abs(pick(period, "capex") or 0.0),
                               pick(period, "dep_amort") or 0.0, pick(period, "cfo"), shares, tags,
                               "eastmoney HK F10 (RPT_HKF10_FN_*_PC, DATE_TYPE_CODE=001)", TAX_DEFAULT["HK"],
                               buybacks=abs(pick(period, "buybacks") or 0.0), dividends=abs(pick(period, "dividends_paid") or 0.0)))
    return rows


def _build_row(market, code, name, period, notice, ccy, rev, opinc, pretax, taxv, intexp, total_eq, parent_eq, minority,
               debt, cash, capex, dep, cfo, shares, tags, src, tax_default, buybacks=0.0, dividends=0.0) -> dict:
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
        "tags_used": ";".join(f"{k}={v}" for k, v in sorted(tags.items())), "source": src,
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
    rows: list[dict] = []
    summary = []
    for r in watch:
        market, code, name = r["market_type"].upper(), r["security_code"], r["security_name"]
        if market == "US":
            c = cik.get(code)
            if not c:
                summary.append(f"{market} {code} {name}: 无 CIK（未上市/无申报），不出行"); continue
            data = sec_download(code, c, args.refresh)
            if not data:
                summary.append(f"{market} {code} {name}: SEC 无数据"); continue
            got = sec_extract(code, name, data)
        elif market == "HK":
            got = hk_extract(code, name, hk_download(code, args.refresh), hk_shares.get(code))
        else:
            summary.append(f"{market} {code} {name}: 该市场无三表取数源，不出行（清单保持无法估值）"); continue
        rows += got
        yrs = [g["period"] for g in got if g.get("nopat") is not None]
        summary.append(f"{market} {code} {name}: {len(got)} 个财年（有 NOPAT {len(yrs)}），{got[-1]['period'] if got else '—'}，币种 {got[-1]['report_currency'] if got else '—'}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in FIELDS})
    print("\n".join(summary))
    print(f"wrote {len(rows)} rows → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

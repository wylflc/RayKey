#!/usr/bin/env python3
"""OI-150 海外估值信号预登记前向检验（美股）：历史时点股票池 → 时点估值 `P/V` → 前向总回报分档。

预登记书：`docs/reports/overseas_pv_forward_prereg.zh.md`（假设、样本、口径、判据在那里锁定；本脚本只执行）。

子命令（全部可重复运行，原始数据缓存在 `data/experiments/exp_oi150_overseas_forward/raw/`，不入库）：
  universe   SEC XBRL frames 逐年营收横截面（四个营收概念取最大）→ 剔除 SIC 6000–6799 → 每年前 N 名 CIK；
             代码与交易所取 `submissions`／`company_tickers_exchange.json`；写 `universe.csv`／`universe_ciks.csv`
  facts      下载股票池全部 CIK 的 companyfacts JSON
  prices     腾讯 `fqkline` 未复权日线（美股符号 us<代码>.<OQ|N|A>），写 `raw/prices/<代码>.csv` 与 `price_index.csv`
  value      逐公司逐月末：事实按 `filed ≤ t` 截断 → `fetch_overseas_statements.sec_extract`／`sec_current_extract`
             → `build_overseas_roic_bands.value_company`（L2 档，rf 取 t 前最新美债 10Y，ERP 常数）→ `pv_monthly.csv`
  report     拆股（SEC 事实＋价跳推断）与分红（SEC 每股宣派）重建总回报 → 前向 3／5 年年化 → 分档、年组 Spearman、判据 → `report.md`

用法::

    python3 scripts/experimental/overseas_pv_forward.py universe --start-cy 2009 --end-cy 2019 --top 400
    python3 scripts/experimental/overseas_pv_forward.py facts
    python3 scripts/experimental/overseas_pv_forward.py prices --threads 4
    python3 scripts/experimental/overseas_pv_forward.py value --workers 32
    python3 scripts/experimental/overseas_pv_forward.py report
    --only AAPL,MSFT 只处理这些代码（管线冒烟用；预登记书允许 ≤ 5 家只验管线、不看分档读数）
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import math
import re
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import build_overseas_roic_bands as bor  # noqa: E402
import fetch_overseas_statements as fos  # noqa: E402
from moat_param_lab import loglinear_fair_pv, spearman  # noqa: E402

EXP = ROOT / "data/experiments/exp_oi150_overseas_forward"
RAW = EXP / "raw"
SEC_HDR = {"User-Agent": fos.UA, "Accept-Encoding": "gzip, deflate"}
TX_HDR = {"User-Agent": "Mozilla/5.0"}
REV_CONCEPTS = ("Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet", "RevenueFromContractWithCustomerExcludingAssessedTax")
SIC_FIN = (6000, 6799)
ERP_US = 0.0446                     # 预登记：ERP 取现行常数（data/reference/overseas_valuation_inputs.csv erp_us）
BUY_LINE, SELL_LINE = 1.0454, 2.4257
BUCKETS = ((0, 0.8), (0.8, BUY_LINE), (BUY_LINE, 1.2), (1.2, 1.6), (1.6, 2.0), (2.0, SELL_LINE), (SELL_LINE, 4.0), (4.0, 99.0))
OBS_FROM, OBS_TO = "2010-04-30", "2021-03-31"
PRICE_FROM = "2007-01-01"
SPLIT_RATIOS = (2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 50)
EXCH_SUFFIX = {"Nasdaq": "OQ", "NYSE": "N", "NYSE American": "A", "NYSE MKT": "A", "CBOE": "N", "OTC": "N"}
SPLIT_CONCEPT = "StockholdersEquityNoteStockSplitConversionRatio1"
DPS_CONCEPTS = ("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid")
SHARES_CONCEPTS = (("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
                   ("us-gaap", "CommonStockSharesOutstanding"))


# ------------------------------------------------------------------ 通用
def _get(url: str, headers: dict, timeout: int = 40, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def _cached_json(path: Path, url: str, headers: dict, sleep: float = 0.12) -> dict | list | None:
    if path.exists() and path.stat().st_size > 200:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        data = _get(url, headers)
    except RuntimeError as exc:
        print(f"  取数失败 {exc}", file=sys.stderr)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    time.sleep(sleep)
    return json.loads(data.decode("utf-8"))


def month_end_dates(start: str, end: str) -> list[str]:
    out, d = [], date.fromisoformat(start)
    while d.isoformat() <= end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = nxt - timedelta(days=1)
        out.append(last.isoformat())
        d = nxt
    return out


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ universe
def doc_ticker(sub: dict | None) -> str:
    """现行代码表与 submissions 都没有代码时（退市／改组为新主体），从 10-K／10-Q 主文档名 `xom-20251231.htm` 取前缀；
    只认「1~5 个字母 + '-' + 8 位日期」的命名且至少 3 份申报一致，代理机构命名（`d358906d10q.htm`）不算。"""
    if not sub:
        return ""
    rec = (sub.get("filings") or {}).get("recent") or {}
    counts: dict[str, int] = defaultdict(int)
    for form, doc in zip(rec.get("form", []), rec.get("primaryDocument", [])):
        if form not in ("10-K", "10-Q", "20-F", "10-K405"):
            continue
        m = re.match(r"([a-z]{1,5})-\d{8}", str(doc).lower())
        if m:
            counts[m.group(1)] += 1
    if not counts:
        return ""
    best, n = max(counts.items(), key=lambda kv: kv[1])
    return best.upper() if n >= 3 else ""


def cmd_universe(args) -> int:
    ticker_map: dict[str, tuple[str, str]] = {}
    ex = _cached_json(RAW / "company_tickers_exchange.json", "https://www.sec.gov/files/company_tickers_exchange.json", SEC_HDR)
    if ex:
        idx = {f: i for i, f in enumerate(ex["fields"])}
        for r in ex["data"]:
            cik = str(r[idx["cik"]]).zfill(10)
            if cik not in ticker_map and r[idx["ticker"]]:
                ticker_map[cik] = (str(r[idx["ticker"]]), str(r[idx["exchange"]] or ""))
    rows, unique = [], {}
    for cy in range(args.start_cy, args.end_cy + 1):
        rev: dict[str, float] = {}
        names: dict[str, str] = {}
        for concept in REV_CONCEPTS:
            fr = _cached_json(RAW / "frames" / f"{concept}_CY{cy}.json",
                              f"https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{cy}.json", SEC_HDR)
            for e in (fr or {}).get("data", []):
                cik = str(e["cik"]).zfill(10)
                v = float(e["val"])
                if v > rev.get(cik, float("-inf")):
                    rev[cik] = v
                    names[cik] = e.get("entityName", "")
        pre = sorted(rev.items(), key=lambda kv: -kv[1])[: args.top * 3 // 2]
        kept = []
        for cik, v in pre:
            sub = _cached_json(RAW / "submissions" / f"CIK{cik}.json", f"https://data.sec.gov/submissions/CIK{cik}.json", SEC_HDR)
            sic = str((sub or {}).get("sic") or "").strip()
            if sic.isdigit() and SIC_FIN[0] <= int(sic) <= SIC_FIN[1]:
                continue
            ticker, exch = "", ""
            if sub and sub.get("tickers"):
                ticker = str(sub["tickers"][0])
                exch = str((sub.get("exchanges") or [""])[0] or "")
            source = "submissions" if ticker else ""
            if not ticker and cik in ticker_map:
                ticker, exch = ticker_map[cik]
                source = "company_tickers_exchange"
            if not ticker:
                ticker, source = doc_ticker(sub), "primary_document"
            if not ticker:
                source = ""
            name = (sub or {}).get("name") or names[cik]
            kept.append(dict(cy=cy, cik=cik, name=name, revenue=f"{v:.0f}", sic=sic, ticker=ticker, exchange=exch,
                             ticker_source=source, obs_from=f"{cy + 1}-04-30", obs_to=f"{cy + 2}-03-31"))
            if len(kept) >= args.top:
                break
        rows += kept
        for r in kept:
            u = unique.setdefault(r["cik"], dict(cik=r["cik"], name=r["name"], ticker=r["ticker"], exchange=r["exchange"],
                                                 ticker_source=r["ticker_source"], sic=r["sic"], years=0))
            u["years"] += 1
        print(f"CY{cy}: 横截面 {len(rev)} 家，入池 {len(kept)}（无代码 {sum(1 for r in kept if not r['ticker'])}）", flush=True)
    write_csv(EXP / "universe.csv", rows, ["cy", "cik", "name", "revenue", "sic", "ticker", "exchange", "ticker_source", "obs_from", "obs_to"])
    write_csv(EXP / "universe_ciks.csv", list(unique.values()), ["cik", "name", "ticker", "exchange", "ticker_source", "sic", "years"])
    print(f"股票池 {len(rows)} 行（{len(unique)} 家；无代码 {sum(1 for u in unique.values() if not u['ticker'])} 家）→ {EXP / 'universe.csv'}")
    return 0


# ------------------------------------------------------------------ facts
def facts_path(cik: str) -> Path:
    return RAW / "sec" / f"CIK{cik}.json"


def cmd_facts(args) -> int:
    ciks = [r["cik"] for r in read_csv(EXP / "universe_ciks.csv")]
    if args.only:
        only = set(args.only.split(","))
        ciks = [r["cik"] for r in read_csv(EXP / "universe_ciks.csv") if r["ticker"] in only]
    ok = miss = 0
    for i, cik in enumerate(ciks, 1):
        d = _cached_json(facts_path(cik), f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", SEC_HDR, sleep=0.15)
        ok += bool(d); miss += not d
        if i % 50 == 0:
            print(f"  {i}/{len(ciks)}", flush=True)
    print(f"companyfacts：{ok} 家已落盘，{miss} 家取不到")
    return 0


# ------------------------------------------------------------------ prices
def tencent_bars(symbol: str, start: str, end: str) -> list[tuple[str, float]]:
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{start},{end},640,"
    d = json.loads(_get(url, TX_HDR, timeout=30))
    data = d.get("data", {}).get(symbol, {})
    return [(b[0], float(b[2])) for b in (data.get("day") or []) if float(b[2]) > 0]


def symbol_candidates(ticker: str, exchange: str) -> list[str]:
    t = ticker.replace("-", ".")
    first = EXCH_SUFFIX.get(exchange, "")
    order = [s for s in (first, "OQ", "N", "A") if s]
    seen, out = set(), []
    for s in order:
        if s not in seen:
            seen.add(s); out.append(f"us{t}.{s}")
    return out


def fetch_price_series(ticker: str, exchange: str) -> tuple[str, list[tuple[str, float]]]:
    for sym in symbol_candidates(ticker, exchange):
        bars: dict[str, float] = {}
        start = date.fromisoformat(PRICE_FROM)
        today = date.today()
        empty_windows = 0
        while start < today:
            end = min(start + timedelta(days=700), today)
            try:
                got = tencent_bars(sym, start.isoformat(), end.isoformat())
            except Exception:  # noqa: BLE001
                got = []
            if got:
                bars.update(got)
            else:
                empty_windows += 1
            start = end + timedelta(days=1)
            time.sleep(0.15)
        if bars:
            return sym, sorted(bars.items())
    return "", []


def price_path(ticker: str) -> Path:
    return RAW / "prices" / f"{ticker.replace('/', '_')}.csv"


def cmd_prices(args) -> int:
    ciks = read_csv(EXP / "universe_ciks.csv")
    todo = [(r["ticker"], r["exchange"]) for r in ciks if r["ticker"]]
    if args.only:
        only = set(args.only.split(","))
        todo = [t for t in todo if t[0] in only]
    todo = sorted(set(todo))
    index_path = EXP / "price_index.csv"
    index = {r["ticker"]: r for r in read_csv(index_path)} if index_path.exists() else {}

    def work(item):
        ticker, exchange = item
        p = price_path(ticker)
        if p.exists() and ticker in index and not args.refresh:
            return ticker, index[ticker]
        sym, series = fetch_price_series(ticker, exchange)
        if series:
            write_csv(p, [dict(date=d, close=f"{c:.4f}") for d, c in series], ["date", "close"])
        row = dict(ticker=ticker, exchange=exchange, symbol=sym, first=series[0][0] if series else "",
                   last=series[-1][0] if series else "", bars=len(series))
        return ticker, row

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        for i, (ticker, row) in enumerate(pool.map(work, todo), 1):
            index[ticker] = row
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
                write_csv(index_path, list(index.values()), ["ticker", "exchange", "symbol", "first", "last", "bars"])
    write_csv(index_path, list(index.values()), ["ticker", "exchange", "symbol", "first", "last", "bars"])
    have = sum(1 for r in index.values() if int(r["bars"] or 0) > 0)
    print(f"价格：{have}/{len(todo)} 个代码有历史价 → {index_path}")
    return 0


# ------------------------------------------------------------------ treasury rf
def load_rf(years: range) -> tuple[list[str], list[float]]:
    pts: dict[str, float] = {}
    for y in years:
        p = RAW / "treasury" / f"{y}.csv"
        if not (p.exists() and p.stat().st_size > 200):
            url = (f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
                   f"?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(_get(url, TX_HDR, timeout=60))
            except RuntimeError as exc:
                print(f"  美债 {y} 取数失败 {exc}", file=sys.stderr)
                continue
        for r in csv.DictReader(p.open(encoding="utf-8-sig")):
            try:
                m, d, yy = r["Date"].split("/")
                v = float(r["10 Yr"])
            except (KeyError, ValueError):
                continue
            pts[f"{yy}-{int(m):02d}-{int(d):02d}"] = v / 100.0
    dates = sorted(pts)
    return dates, [pts[d] for d in dates]


def rf_at(dates: list[str], vals: list[float], t: str) -> float | None:
    i = bisect.bisect_right(dates, t) - 1
    return vals[i] if i >= 0 else None


# ------------------------------------------------------------------ value (PIT)
def split_events(facts: dict) -> list[tuple[str, float]]:
    node = (facts.get("us-gaap") or {}).get(SPLIT_CONCEPT) or {}
    out: dict[str, float] = {}
    for e in (node.get("units") or {}).get("pure", []):
        try:
            k, end = float(e["val"]), str(e.get("end") or "")
        except (KeyError, ValueError, TypeError):
            continue
        if end and k > 0 and abs(k - 1.0) > 1e-9:
            out[end] = k
    return sorted(out.items())


def shares_series(facts: dict) -> list[tuple[str, float]]:
    pts: dict[str, float] = {}
    for tax, concept in SHARES_CONCEPTS:
        node = (facts.get(tax) or {}).get(concept) or {}
        for e in (node.get("units") or {}).get("shares", []):
            end = str(e.get("end") or "")
            if end and not pts.get(end):
                try:
                    pts[end] = float(e["val"])
                except (KeyError, ValueError, TypeError):
                    continue
        if pts:
            break
    return sorted(pts.items())


def inferred_splits(prices: list[tuple[str, float]], shares: list[tuple[str, float]], known: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """无 SEC 拆股事实时，相邻两日收盘比落在拆股比 ±3% 且随后一期股数同倍变化（±10%）者记为拆股。"""
    out = []
    known_days = [date.fromisoformat(d) for d, _ in known]
    sh_dates = [d for d, _ in shares]
    for i in range(1, len(prices)):
        d0, c0 = prices[i - 1]
        d1, c1 = prices[i]
        if c1 <= 0 or c0 <= 0:
            continue
        r = c0 / c1
        cand = None
        for k in SPLIT_RATIOS:
            if abs(r / k - 1) <= 0.03:
                cand = float(k)
            elif abs(r * k - 1) <= 0.03:
                cand = 1.0 / k
        if cand is None:
            continue
        dd = date.fromisoformat(d1)
        if any(abs((dd - kd).days) <= 7 for kd in known_days):
            continue
        j = bisect.bisect_left(sh_dates, d1)
        before = shares[j - 1][1] if j - 1 >= 0 else None
        after = shares[j][1] if j < len(shares) else None
        if before and after and abs(after / before / cand - 1) <= 0.10:
            out.append((d1, cand))
    return out


def dividend_events(facts: dict) -> list[tuple[str, float]]:
    """季度每股宣派股息：同一 (start, end) 取最新申报；期长 60~120 日。"""
    best: dict[tuple[str, str], tuple[str, float]] = {}
    for concept in DPS_CONCEPTS:
        node = (facts.get("us-gaap") or {}).get(concept) or {}
        for e in (node.get("units") or {}).get("USD/shares", []):
            start, end, filed = str(e.get("start") or ""), str(e.get("end") or ""), str(e.get("filed") or "")
            if not start or not end:
                continue
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            if not 60 <= days <= 120:
                continue
            try:
                v = float(e["val"])
            except (KeyError, ValueError, TypeError):
                continue
            if v <= 0:
                continue
            key = (start, end)
            if key not in best or best[key][0] < filed:
                best[key] = (filed, v)
        if best:
            break
    return sorted((end, v) for (_s, end), (_f, v) in best.items())


class PitFacts:
    """companyfacts 按申报日截断：每个概念的条目按 filed 排序，`at(t)` 返回只含 filed ≤ t 条目的事实字典。"""

    def __init__(self, facts: dict):
        self.tax_name = "ifrs-full" if ("ifrs-full" in facts and "ProfitLossBeforeTax" in facts["ifrs-full"]) else "us-gaap"
        self.sorted: dict[str, dict[str, tuple[list[str], list[dict]]]] = {}
        for concept, node in (facts.get(self.tax_name) or {}).items():
            per_unit = {}
            for unit, entries in (node.get("units") or {}).items():
                es = sorted(entries, key=lambda e: str(e.get("filed") or ""))
                per_unit[unit] = ([str(e.get("filed") or "") for e in es], es)
            self.sorted[concept] = per_unit

    def at(self, t: str) -> dict:
        tax: dict = {}
        for concept, per_unit in self.sorted.items():
            units = {}
            for unit, (filed, es) in per_unit.items():
                n = bisect.bisect_right(filed, t)
                if n:
                    units[unit] = es[:n]
            if units:
                tax[concept] = {"units": units}
        return tax


def value_worker(job: dict) -> list[dict]:
    cik, ticker, name, obs = job["cik"], job["ticker"], job["name"], job["obs"]
    rf_dates, rf_vals = job["rf"]
    out: list[dict] = []
    p = facts_path(cik)
    if not p.exists():
        return [dict(cik=cik, ticker=ticker, date=t, status="no_facts", reason="", price="", value="", pv="", period="", rf="") for t in obs]
    facts = json.loads(p.read_text(encoding="utf-8")).get("facts", {})
    pit = PitFacts(facts)
    maps = fos.IFRS if pit.tax_name == "ifrs-full" else fos.GAAP
    splits = split_events(facts)
    prices: list[tuple[str, float]] = []
    pp = price_path(ticker) if ticker else None
    if pp and pp.exists():
        prices = [(r["date"], float(r["close"])) for r in read_csv(pp)]
    pdates = [d for d, _ in prices]
    if prices:
        splits = sorted(set(splits) | set(inferred_splits(prices, shares_series(facts), splits)))
    for t in obs:
        row = dict(cik=cik, ticker=ticker, date=t, status="", reason="", price="", value="", pv="", period="", rf="")
        i = bisect.bisect_right(pdates, t) - 1
        price = prices[i][1] if (i >= 0 and (date.fromisoformat(t) - date.fromisoformat(pdates[i])).days <= 7) else None
        rf = rf_at(rf_dates, rf_vals, t)
        row["rf"] = f"{rf:.4f}" if rf is not None else ""
        tax = pit.at(t)
        annuals = fos.sec_extract(ticker or cik, name, {"facts": {pit.tax_name: tax}})
        if not annuals:
            row["status"], row["reason"] = "no_annual", "无 filed≤t 的年报行"
            out.append(row); continue
        current = fos.sec_current_extract(ticker or cik, name, tax, maps, annuals)
        years = [bor.year_from_row(r) for r in annuals]
        cur = bor.year_from_row(current) if current else None
        if rf is None:
            row["status"], row["reason"] = "no_rf", ""
            out.append(row); continue
        try:
            res = bor.value_company(ticker or cik, "L2", years, {"rf_usd": rf, "erp_us": ERP_US}, cur)
        except Exception as exc:  # noqa: BLE001
            row["status"], row["reason"] = "error", str(exc)[:80]
            out.append(row); continue
        latest_period = cur.period if (cur and cur.period > years[-1].period) else years[-1].period
        row["period"] = latest_period
        if res.get("status") != "ok":
            row["status"], row["reason"] = "rejected", str(res.get("reason", ""))[:80]
            out.append(row); continue
        factor = 1.0
        for d, k in splits:
            if latest_period < d <= t:
                factor *= k
        value = res["value"] / factor
        row["value"] = f"{value:.4f}"
        if price is None:
            row["status"] = "no_price"
        else:
            row["status"], row["price"], row["pv"] = "ok", f"{price:.4f}", f"{price / value:.4f}"
        out.append(row)
    return out


def cmd_value(args) -> int:
    uni = read_csv(EXP / "universe.csv")
    ciks = read_csv(EXP / "universe_ciks.csv")
    info = {r["cik"]: r for r in ciks}
    obs_by_cik: dict[str, set[str]] = defaultdict(set)
    for r in uni:
        for t in month_end_dates(r["obs_from"], r["obs_to"]):
            if OBS_FROM <= t <= OBS_TO:
                obs_by_cik[r["cik"]].add(t)
    rf = load_rf(range(2009, date.today().year + 1))
    print(f"美债 10Y 观测 {len(rf[0])} 个交易日（{rf[0][0] if rf[0] else '—'}～{rf[0][-1] if rf[0] else '—'}）")
    jobs = []
    for cik, obs in sorted(obs_by_cik.items()):
        r = info[cik]
        if args.only and r["ticker"] not in set(args.only.split(",")):
            continue
        jobs.append(dict(cik=cik, ticker=r["ticker"], name=r["name"], obs=sorted(obs), rf=rf))
    print(f"逐月时点估值：{len(jobs)} 家 × 月末（共 {sum(len(j['obs']) for j in jobs)} 个观测），{args.workers} 并发", flush=True)
    fields = ["cik", "ticker", "date", "status", "reason", "price", "value", "pv", "period", "rf"]
    EXP.mkdir(parents=True, exist_ok=True)
    out_path = EXP / ("pv_monthly.csv" if not args.only else "pv_monthly_smoke.csv")
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        if args.workers > 1:
            with Pool(args.workers) as pool:
                for i, rows in enumerate(pool.imap_unordered(value_worker, jobs), 1):
                    w.writerows(rows); fh.flush()
                    if i % 25 == 0:
                        print(f"  {i}/{len(jobs)}", flush=True)
        else:
            for i, job in enumerate(jobs, 1):
                w.writerows(value_worker(job)); fh.flush()
    print(f"→ {out_path}")
    return 0


# ------------------------------------------------------------------ report
def total_return_series(prices: list[tuple[str, float]], splits: list[tuple[str, float]], divs: list[tuple[str, float]]) -> dict[str, float]:
    """持 1 股：拆股按比例加股（拆股日），季度每股宣派股息按季末后首个交易日收盘再投。"""
    pdates = [d for d, _ in prices]
    by_day: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for d, k in splits:
        by_day[d].append(("split", k))
    for end, v in divs:
        j = bisect.bisect_left(pdates, end)
        if j < len(pdates):
            by_day[pdates[j]].append(("div", v))
    shares, out = 1.0, {}
    for d, close in prices:
        for kind, v in by_day.get(d, ()):
            if kind == "split":
                shares *= v
            elif close > 0:
                shares += shares * v / close
        out[d] = shares * close
    return out


def forward_return(tr: dict[str, float], days: list[str], start: str, years: int, data_end: str) -> tuple[float | None, str]:
    """前向年化；序列在目标日前结束且早于数据末端 15 天以上视为退市，以末价为终值、此后按现金零收益年化。"""
    d0 = date.fromisoformat(start)
    try:
        target = d0.replace(year=d0.year + years).isoformat()
    except ValueError:
        target = d0.replace(year=d0.year + years, day=28).isoformat()
    i = bisect.bisect_right(days, target) - 1
    if i < 0 or days[i] <= start or tr.get(start, 0) <= 0:
        return None, "no_start"
    end = days[i]
    if (date.fromisoformat(end) - d0).days >= years * 365 - 10:
        return (tr[end] / tr[start]) ** (1 / years) - 1, "full"
    if days[-1] < (date.fromisoformat(data_end) - timedelta(days=15)).isoformat():
        return (tr[days[-1]] / tr[start]) ** (1 / years) - 1, "delisted_terminal"
    return None, "window_incomplete"


def bucket_of(pv: float) -> str:
    for lo, hi in BUCKETS:
        if lo <= pv < hi:
            return f"[{lo:g},{hi:g})"
    return "NA"


def year_group(t: str) -> int:
    y, m = int(t[:4]), int(t[5:7])
    return y if m >= 4 else y - 1


def cmd_report(args) -> int:
    pv_rows = read_csv(EXP / ("pv_monthly.csv" if not args.only else "pv_monthly_smoke.csv"))
    ciks = {r["cik"]: r for r in read_csv(EXP / "universe_ciks.csv")}
    lines: list[str] = []

    def say(s: str = "") -> None:
        print(s); lines.append(s)

    say("# OI-150 美股估值信号前向检验报告（预登记：docs/reports/overseas_pv_forward_prereg.zh.md）")
    say(f"生成 {date.today().isoformat()}；观测期 {OBS_FROM}～{OBS_TO} 月末；分档 {'、'.join(f'[{lo:g},{hi:g})' for lo, hi in BUCKETS)}")
    # 1. 覆盖与剔除
    status = defaultdict(int)
    for r in pv_rows:
        status[r["status"]] += 1
    n_all = len(pv_rows)
    no_ticker = sum(1 for r in pv_rows if not r["ticker"])
    say("\n## 1. 覆盖与剔除（公司-月）")
    say("| 状态 | 数量 | 占比 |\n| --- | ---: | ---: |")
    for k, v in sorted(status.items(), key=lambda kv: -kv[1]):
        say(f"| {k} | {v} | {v / n_all * 100:.1f}% |")
    say(f"无代码（no_ticker）{no_ticker}（{no_ticker / n_all * 100:.1f}%）；rejected 原因分布见附表。")
    reasons = defaultdict(int)
    for r in pv_rows:
        if r["status"] == "rejected":
            reasons[r["reason"][:24]] += 1
    say("| 拒绝原因（前 24 字） | 数量 |\n| --- | ---: |")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:12]:
        say(f"| {k} | {v} |")
    # 2. 前向回报
    ok = [r for r in pv_rows if r["status"] == "ok"]
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        by_ticker[r["ticker"]].append(r)
    data_end = ""
    obs = []          # (ticker, t, pv, fwd3, fwd5, kind3, kind5)
    tr_cache: dict[str, tuple[dict, list[str]]] = {}
    for ticker, rows in by_ticker.items():
        pp = price_path(ticker)
        if not pp.exists():
            continue
        prices = [(r["date"], float(r["close"])) for r in read_csv(pp)]
        data_end = max(data_end, prices[-1][0])
    for ticker, rows in by_ticker.items():
        pp = price_path(ticker)
        if not pp.exists():
            continue
        prices = [(r["date"], float(r["close"])) for r in read_csv(pp)]
        cik = rows[0]["cik"]
        facts = json.loads(facts_path(cik).read_text(encoding="utf-8")).get("facts", {})
        splits = sorted(set(split_events(facts)) | set(inferred_splits(prices, shares_series(facts), split_events(facts))))
        divs = dividend_events(facts)
        tr = total_return_series(prices, splits, divs)
        days = [d for d, _ in prices]
        for r in rows:
            t = r["date"]
            i = bisect.bisect_right(days, t) - 1
            if i < 0:
                continue
            start = days[i]
            f3, k3 = forward_return(tr, days, start, 3, data_end)
            f5, k5 = forward_return(tr, days, start, 5, data_end)
            obs.append((ticker, t, float(r["pv"]), f3, f5, k3, k5, len(splits), len(divs)))
    say(f"\n## 2. 前向总回报（数据末端 {data_end}；拆股按 SEC 事实＋价跳推断，分红按季度每股宣派再投）")
    say(f"可估值观测 {len(ok)}，有前向 3 年读数 {sum(1 for o in obs if o[3] is not None)}，5 年 {sum(1 for o in obs if o[4] is not None)}；"
        f"退市末价终值：3 年 {sum(1 for o in obs if o[5] == 'delisted_terminal')}、5 年 {sum(1 for o in obs if o[6] == 'delisted_terminal')}")
    # 3. 分档
    for h, idx in ((3, 3), (5, 4)):
        say(f"\n## 3.{1 if h == 3 else 2} 前向 {h} 年年化按 `P/V` 分档（中位，pp）")
        say("| 档 | 观测数 | 公司数 | 中位 | P25 | P75 | 年组数 |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        med_by_bucket = {}
        for lo, hi in BUCKETS:
            key = f"[{lo:g},{hi:g})"
            sel = [o for o in obs if o[idx] is not None and lo <= o[2] < hi]
            if not sel:
                say(f"| {key} | 0 | 0 | — | — | — | 0 |"); continue
            vals = sorted(o[idx] for o in sel)
            q = lambda p: vals[min(len(vals) - 1, int(p * len(vals)))]
            med_by_bucket[key] = statistics.median(vals)
            say(f"| {key} | {len(sel)} | {len({o[0] for o in sel})} | {statistics.median(vals) * 100:.2f} | {q(0.25) * 100:.2f} | {q(0.75) * 100:.2f} | {len({year_group(o[1]) for o in sel})} |")
        groups = defaultdict(list)
        for o in obs:
            if o[idx] is not None:
                groups[year_group(o[1])].append((o[2], o[idx]))
        say(f"\n年组 Spearman(P/V, 前向 {h} 年)（每年 4 月末～次年 3 月末为一组；样本 < 30 的组不计）：")
        say("| 年组 | 观测 | Spearman | 各档中位（前四档） |\n| --- | ---: | ---: | --- |")
        neg = tot = 0
        for g in sorted(groups):
            pairs = groups[g]
            if len(pairs) < 30:
                continue
            rho = spearman([p for p, _ in pairs], [f for _, f in pairs])
            tot += 1; neg += rho < 0
            meds = []
            for lo, hi in BUCKETS[:4]:
                v = [f for p, f in pairs if lo <= p < hi]
                meds.append(f"{statistics.median(v) * 100:.1f}" if v else "—")
            say(f"| {g} | {len(pairs)} | {rho:+.3f} | {' / '.join(meds)} |")
        all_pairs = [(o[2], o[idx]) for o in obs if o[idx] is not None and o[2] > 0]
        fair = loglinear_fair_pv(all_pairs, 0.09) if all_pairs else None
        cheap, mid = med_by_bucket.get(f"[0.8,{BUY_LINE:g})"), med_by_bucket.get("[1.2,1.6)")
        gap = (cheap - mid) * 100 if (cheap is not None and mid is not None) else None
        say(f"\n判据 {h} 年：负号年组 {neg}/{tot}（要求 ≥ 2/3）；[0.8,{BUY_LINE:g}) 中位 − [1.2,1.6) 中位 = {f'{gap:+.2f}pp' if gap is not None else '—'}（要求 ≥ +3pp）；"
            f"全样本 Spearman {spearman([p for p, _ in all_pairs], [f for _, f in all_pairs]):+.3f}；对数线性公允点（前向 = 9%）{f'{fair:.2f}' if fair else '无解'}")
        passed = tot > 0 and neg >= math.ceil(2 * tot / 3) and gap is not None and gap >= 3.0
        say(f"**结论（{h} 年）**：{'支持 H1' if passed else '不支持 H1'}")
    # 4. 剔除阈值
    excl = status.get("no_price", 0) + no_ticker
    say(f"\n## 4. 剔除阈值核对：no_ticker + no_price = {excl}（{excl / n_all * 100:.1f}%，阈值 15%）；"
        f"{'超阈值 → 结论降级为「不可判」' if excl / n_all > 0.15 else '未超阈值'}")
    (EXP / ("report.md" if not args.only else "report_smoke.md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("universe"); u.add_argument("--start-cy", type=int, default=2009); u.add_argument("--end-cy", type=int, default=2019)
    u.add_argument("--top", type=int, default=400); u.set_defaults(fn=cmd_universe)
    f = sub.add_parser("facts"); f.add_argument("--only", default=""); f.set_defaults(fn=cmd_facts)
    p = sub.add_parser("prices"); p.add_argument("--threads", type=int, default=4); p.add_argument("--only", default="")
    p.add_argument("--refresh", action="store_true"); p.set_defaults(fn=cmd_prices)
    v = sub.add_parser("value"); v.add_argument("--workers", type=int, default=8); v.add_argument("--only", default=""); v.set_defaults(fn=cmd_value)
    r = sub.add_parser("report"); r.add_argument("--only", default=""); r.set_defaults(fn=cmd_report)
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

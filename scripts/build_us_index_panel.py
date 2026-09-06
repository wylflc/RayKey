#!/usr/bin/env python3
"""OI-159 美股标普 500 历史成分 → 时点股票库面板（`panel_moat_bank_v6b.csv` 同格式，`security_code` = 10 位 CIK）。

预登记：`docs/reports/us_sp500_backtest_prereg.zh.md` §2。

输入（缓存到 `data/experiments/exp_us_sp500_port/raw/`，不入库；`--refresh` 强制重取）：
  sp500/components.csv        GitHub fja05680/sp500 每日成分快照（`date,tickers`），manifest.json 记下载日与 SHA-256
  wiki/list.html              维基 List of S&P 500 companies（现役成分表带 CIK）
  sec/company_tickers.json    SEC 现行代码表
  submissions/CIK*.json       SEC submissions（名称、SIC、现行代码、申报区间）；OI-150 已缓存的直接复用
代码 → CIK 候选逐层收集（每个区间可有多个候选）：
  override  `data/reference/us_ticker_cik_overrides.csv`（ticker,from,to,cik,price_ticker,basis；price_ticker 为取价用的历史代码）
  wiki      维基现役表 CIK
  sec       `company_tickers.json`
  wayback   SEC `company_tickers.json` 的 Wayback 历史快照（2017-08 起逐年两份）：快照日落在区间内即为强证据
  oi150     OI-150 `universe_ciks.csv`（含退市大公司，代码取自申报文件命名）
  rename    区间末日与另一代码区间首日相邻（≤ 7 天）的后者所解析到的 CIK（同一公司改名的候选）
  efts      EDGAR 全文检索 `q="<代码>"`（另试去掉股份类别后缀的代码）、10-K、区间内 → 命中最多的前 5 个 CIK
**申报文件核实**：该 CIK 在区间内 10-K／10-Q 的 XBRL 实例文件名或主文档名前缀等于本代码（`fb-20161231.xml`、
`xom-20251231.htm`；允许 GOOG／GOOGL 这类一位股份类别后缀之差），从最近的申报往前查。已结束的区间除 override 与
快照落在区间内的 wayback 外一律须核实（防代码复用，如 BBBY）；`rename`／`efts` 候选另须在区间内有公众持股（
companyfacts `dei:EntityPublicFloat`），排除与母公司合并申报的子公司（BGE 之于 CEG）。
每个候选取 submissions 申报区间 [首次, 末次]；按面板窗口裁剪后的成员区间用候选**拼接覆盖**：从区间起点起选首次申报
≤ 当前日 + 400 天的候选，段止 = min(区间止, 该 CIK 末次申报, 下一候选首次申报 − 1)——控股公司重组换 CIK
（Apache → APA、Avago → Broadcom）即拆成两段两个 `security_code`，视同出入指数。覆盖不到的余段记 `no_cik`。
金融（SIC 6000–6799）不进面板、单独计数；SIC 缺失保留并标注。

输出：
  data/processed/pit_attention/panel_sp500_us.csv   面板（effective_from,effective_to,screen_year,security_code,security_name,avg_roe_3y,rank）
  data/processed/us_sp500_members.csv               逐区间成员表（代码、CIK、来源、名称、SIC、状态、现行代码、申报区间）
  data/interim/us_sp500_panel_audit.csv             未解析与校验失败明细
用法：
    python3 scripts/build_us_index_panel.py [--panel-start 2009-01-01] [--refresh]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data/experiments/exp_us_sp500_port"
RAW = EXP / "raw"
OI150_RAW = ROOT / "data/experiments/exp_oi150_overseas_forward/raw"
OI150_CIKS = ROOT / "data/experiments/exp_oi150_overseas_forward/universe_ciks.csv"
OVERRIDES = ROOT / "data/reference/us_ticker_cik_overrides.csv"
PANEL_OUT = ROOT / "data/processed/pit_attention/panel_sp500_us.csv"
MEMBERS_OUT = ROOT / "data/processed/us_sp500_members.csv"
AUDIT_OUT = ROOT / "data/interim/us_sp500_panel_audit.csv"

COMPONENTS_URL = ("https://raw.githubusercontent.com/fja05680/sp500/master/"
                  "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv")
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_HDR = {"User-Agent": "RayKey research wzq9464@gmail.com", "Accept-Encoding": "identity"}
WEB_HDR = {"User-Agent": "Mozilla/5.0"}
SIC_FIN = (6000, 6799)
SPAN_TOL = 400          # 天：申报区间对成员区间的容差
PRIORITY = {"override": 0, "wiki": 1, "sec": 1, "wayback": 2, "oi150": 3, "rename": 4, "efts": 5}
WAYBACK_URL = "https://web.archive.org/web/{ts}id_/https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
XBRL_FROM = "2009-06-01"  # 申报文件核实只能用带 XBRL 实例的申报
EFTS_URL = "https://efts.sec.gov/LATEST/search-index?q=%22{q}%22&forms=10-K&dateRange=custom&startdt={a}&enddt={b}"
VERIFY_FORMS = ("10-K", "10-K405", "20-F", "10-Q")


def _get(url: str, headers: dict, timeout: int = 60, retries: int = 3) -> bytes:
    last: Exception | None = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET {url}: {last}")


def cached(path: Path, url: str, headers: dict, refresh: bool, sleep: float = 0.0) -> bytes | None:
    if path.exists() and not refresh:
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = _get(url, headers)
    except RuntimeError as exc:
        print(f"  取数失败：{exc}", file=sys.stderr)
        return None
    path.write_bytes(data)
    if sleep:
        time.sleep(sleep)
    return data


def cik10(v) -> str:
    return str(int(v)).zfill(10)


# ------------------------------------------------------------------ 成分快照 → 区间
def load_components(refresh: bool) -> list[tuple[str, set[str]]]:
    path = RAW / "sp500/components.csv"
    data = cached(path, COMPONENTS_URL, WEB_HDR, refresh)
    if data is None:
        sys.exit("成分快照不可得")
    manifest = RAW / "sp500/manifest.json"
    if refresh or not manifest.exists():
        manifest.write_text(json.dumps({"url": COMPONENTS_URL, "fetched": date.today().isoformat(),
                                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}, indent=1))
    rows = list(csv.DictReader(data.decode("utf-8").splitlines()))
    out = []
    for r in rows:
        tickers = {t.strip().upper() for t in r["tickers"].split(",") if t.strip()}
        out.append((r["date"], tickers))
    out.sort()
    return out


def snapshots_to_intervals(snaps: list[tuple[str, set[str]]]) -> list[dict]:
    """连续快照中持续出现 → 一个区间；消失日的前一天为止；末个快照仍在 → 开放区间。"""
    open_from: dict[str, str] = {}
    intervals: list[dict] = []
    prev: set[str] = set()
    for i, (d, members) in enumerate(snaps):
        for t in members - prev:
            open_from[t] = d
        for t in prev - members:
            end = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
            intervals.append({"ticker": t, "from": open_from.pop(t), "to": end})
        prev = members
    for t, f in open_from.items():
        intervals.append({"ticker": t, "from": f, "to": ""})
    intervals.sort(key=lambda r: (r["ticker"], r["from"]))
    return intervals


# ------------------------------------------------------------------ 代码 → CIK 各层
def wiki_ciks(refresh: bool) -> dict[str, list[str]]:
    data = cached(RAW / "wiki/list.html", WIKI_URL, WEB_HDR, refresh)
    out: dict[str, list[str]] = {}
    if data is None:
        return out
    s = data.decode("utf-8", "replace")
    m = re.search(r'<table[^>]*id="constituents"[^>]*>(.*?)</table>', s, re.S)
    if not m:
        return out
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 7 and re.fullmatch(r"\d{5,10}", cells[6]):
            out.setdefault(cells[0].upper(), []).append(cik10(cells[6]))
    return out


def sec_ticker_map(refresh: bool) -> dict[str, list[str]]:
    data = cached(RAW / "sec/company_tickers.json", SEC_TICKERS_URL, SEC_HDR, refresh)
    out: dict[str, list[str]] = {}
    if data is None:
        return out
    for v in json.loads(data).values():
        t = str(v.get("ticker", "")).upper().replace("-", ".")
        if t and cik10(v["cik_str"]) not in out.setdefault(t, []):
            out[t].append(cik10(v["cik_str"]))
    return out


def oi150_map() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not OI150_CIKS.exists():
        return out
    for r in csv.DictReader(OI150_CIKS.open(encoding="utf-8")):
        t = (r.get("ticker") or "").upper().replace("-", ".")
        if t and cik10(r["cik"]) not in out.setdefault(t, []):
            out[t].append(cik10(r["cik"]))
    return out


def overrides() -> list[dict]:
    if not OVERRIDES.exists():
        return []
    return list(csv.DictReader(OVERRIDES.open(encoding="utf-8")))


# ------------------------------------------------------------------ submissions
class Submissions:
    def __init__(self, refresh: bool):
        self.refresh = refresh
        self.span_cache: dict[str, tuple[str, str]] = {}      # 只缓存派生的小结果：整份 submissions／companyfacts 不驻留内存
        self.info_cache: dict[str, dict] = {}
        self.float_cache: dict[str, list[tuple[str, float]]] = {}

    def get(self, cik: str) -> dict | None:
        name = f"CIK{cik}.json"
        path = RAW / "submissions" / name
        alt = OI150_RAW / "submissions" / name
        if not path.exists() and alt.exists() and not self.refresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(alt.read_bytes())
        data = cached(path, f"https://data.sec.gov/submissions/{name}", SEC_HDR, self.refresh, sleep=0.11)
        return json.loads(data) if data else None

    def _derive(self, cik: str) -> None:
        sub = self.get(cik) or {}
        rec = (sub.get("filings") or {}).get("recent") or {}
        dates = [d for d in rec.get("filingDate", []) if d]
        first = min(dates) if dates else ""
        last = max(dates) if dates else ""
        for f in (sub.get("filings") or {}).get("files") or []:
            if f.get("filingFrom") and (not first or f["filingFrom"] < first):
                first = f["filingFrom"]
        self.span_cache[cik] = (first, last)
        self.info_cache[cik] = {"name": sub.get("name", ""), "sic": str(sub.get("sic") or ""),
                                "current_ticker": (sub.get("tickers") or [""])[0] if sub.get("tickers") else "",
                                "exchange": (sub.get("exchanges") or [""])[0] or "" if sub.get("exchanges") else ""}

    def span(self, cik: str) -> tuple[str, str]:
        if cik not in self.span_cache:
            self._derive(cik)
        return self.span_cache[cik]

    def info(self, cik: str) -> dict:
        if cik not in self.info_cache:
            self._derive(cik)
        return self.info_cache[cik]

    def filings(self, cik: str, lo: str, hi: str) -> list[tuple[str, str, str, str]]:
        """[(form, accession, filingDate, primaryDocument)]，申报日在 [lo, hi] 内；早于 recent 的翻分页文件。"""
        sub = self.get(cik)
        if not sub:
            return []
        out = []

        def take(rec: dict) -> None:
            for f, a, d, doc in zip(rec.get("form", []), rec.get("accessionNumber", []), rec.get("filingDate", []), rec.get("primaryDocument", [])):
                if lo <= d <= hi and f in VERIFY_FORMS:
                    out.append((f, a, d, doc))
        rec = (sub.get("filings") or {}).get("recent") or {}
        take(rec)
        dates = [d for d in rec.get("filingDate", []) if d]
        if dates and lo < min(dates):
            for pg in (sub.get("filings") or {}).get("files") or []:
                if pg.get("filingTo", "") < lo or pg.get("filingFrom", "9999") > hi:
                    continue
                data = cached(RAW / "submissions" / pg["name"], f"https://data.sec.gov/submissions/{pg['name']}", SEC_HDR, False, sleep=0.11)
                if data:
                    take(json.loads(data))
        # 年报优先、由近及远
        out.sort(key=lambda x: (1 if x[0] == "10-Q" else 0, x[2]), reverse=False)
        annual = sorted([x for x in out if x[0] != "10-Q"], key=lambda x: x[2], reverse=True)
        quarterly = sorted([x for x in out if x[0] == "10-Q"], key=lambda x: x[2], reverse=True)
        return annual + quarterly

    def instance_tickers(self, cik: str, lo: str, hi: str, target: str = "", limit: int = 8) -> set[str]:
        """区间内申报的 XBRL 实例文件名／主文档名前缀里的代码（小写字母数字）；给了 target 则找到即停。"""
        found: set[str] = set()
        n = 0
        for form, accn, d, doc in self.filings(cik, max(lo, XBRL_FROM), hi):
            m = re.match(r"([a-z0-9]{1,6})-\d{8}", str(doc).lower())
            if m:
                found.add(m.group(1))
            else:
                idx_name = f"CIK{cik}_{accn}.json"
                path = RAW / "filing_index" / idx_name
                alt = OI150_RAW / "filing_index" / idx_name
                if not path.exists() and alt.exists():
                    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(alt.read_bytes())
                data = cached(path, f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/index.json", SEC_HDR, False, sleep=0.11)
                items = (((json.loads(data) if data else {}).get("directory") or {}).get("item") or [])
                for it in items:
                    mm = re.match(r"^([a-z0-9]{1,6})-\d{8}(?:_htm)?\.xml$", str(it.get("name", "")).lower())
                    if mm:
                        found.add(mm.group(1)); break
            n += 1
            if target and any(ticker_match(target, f) for f in found):
                break
            if n >= limit:
                break
        return found

    def public_float_series(self, cik: str) -> list[tuple[str, float]]:
        """companyfacts（缓存到 raw/sec，估值步复用）里的 dei:EntityPublicFloat [(申报日, 值)]；只留这一小段。"""
        if cik in self.float_cache:
            return self.float_cache[cik]
        name = f"CIK{cik}.json"
        path = RAW / "sec" / name
        alt = OI150_RAW / "sec" / name
        if not path.exists() and alt.exists():
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(alt.read_bytes())
        data = cached(path, SEC_FACTS_URL.format(cik=cik), SEC_HDR, False, sleep=0.11)
        series: list[tuple[str, float]] = []
        if data:
            facts = json.loads(data)
            for e in ((((facts.get("facts") or {}).get("dei") or {}).get("EntityPublicFloat") or {}).get("units") or {}).get("USD", []):
                series.append((str(e.get("filed") or ""), float(e.get("val") or 0)))
            del facts
        self.float_cache[cik] = series
        return series

    def public_float(self, cik: str, lo: str, hi: str) -> float:
        """区间内申报的公众持股市值最大值（没有即 0：全资子公司合并申报）。"""
        return max((v for d, v in self.public_float_series(cik) if lo <= d <= hi), default=0.0)


def norm_ticker(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def ticker_match(ticker: str, found: str) -> bool:
    """相等；或只差一位股份类别后缀（goog／googl、brk／brkb、fox／foxa）；或实例名 = 代码 + 至多两位法人后缀（nlsn／nlsnnv）。"""
    a, b = norm_ticker(ticker), norm_ticker(found)
    if a == b:
        return True
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    if len(short) >= 2 and len(long_) == len(short) + 1 and long_.startswith(short):
        return True
    return len(a) >= 3 and b.startswith(a) and len(b) - len(a) <= 2


def efts_candidates(ticker: str, lo: str, hi: str, refresh: bool) -> list[str]:
    """EDGAR 全文检索按代码短语找 10-K → 命中最多的前 5 个 CIK（另试去掉一位股份类别后缀的代码）。"""
    lo = max(lo, "2001-01-01")
    variants = [ticker]
    base = re.sub(r"\.[A-Z]$", "", ticker)
    if base != ticker:
        variants.append(base)
    elif len(ticker) >= 4 and ticker[-1] in "ABCK":
        variants.append(ticker[:-1])
    c: Counter = Counter()
    for q in variants:
        path = RAW / "efts" / f"{norm_ticker(q)}_{lo}_{hi}.json"
        data = cached(path, EFTS_URL.format(q=urllib.parse.quote(q), a=lo, b=hi), SEC_HDR, refresh, sleep=0.15)
        if not data:
            continue
        try:
            hits = (json.loads(data).get("hits") or {}).get("hits") or []
        except json.JSONDecodeError:
            continue
        for h in hits:
            for ck in (h.get("_source") or {}).get("ciks") or []:
                c[cik10(ck)] += 1
    return [ck for ck, _ in c.most_common(5)]


def wayback_maps(refresh: bool) -> dict[str, list[tuple[str, str]]]:
    """{代码: [(cik, 快照日)]}：SEC company_tickers.json 的历史快照（Wayback，2017-08 起）。"""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen_ts: set[str] = set()
    for year in range(2017, date.today().year + 1):
        for md in ("0101", "0701"):
            ts = f"{year}{md}"
            path = RAW / "wayback" / f"company_tickers_{ts}.json"
            meta = RAW / "wayback" / f"company_tickers_{ts}.meta"
            if (not path.exists() or refresh):
                try:
                    with urllib.request.urlopen(urllib.request.Request(WAYBACK_URL.format(ts=ts), headers=WEB_HDR), timeout=90) as r:
                        body = r.read(); final = r.geturl()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body); meta.write_text(final)
                    time.sleep(1.0)
                except Exception as exc:  # noqa: BLE001
                    print(f"  wayback {ts} 失败：{exc}", file=sys.stderr); continue
            m = re.search(r"/web/(\d{8})", meta.read_text() if meta.exists() else "")
            snap = m.group(1) if m else ts
            if snap in seen_ts:
                continue
            seen_ts.add(snap)
            snap_date = f"{snap[:4]}-{snap[4:6]}-{snap[6:8]}"
            body = path.read_bytes()
            if body[:2] == b"\x1f\x8b":            # Wayback 原样返回归档时的 gzip 编码
                body = gzip.decompress(body)
            try:
                d = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for v in (d.values() if isinstance(d, dict) else d):
                t = str(v.get("ticker", "")).upper().replace("-", ".")
                if t:
                    out[t].append((cik10(v["cik_str"]), snap_date))
    print(f"Wayback 快照 {len(seen_ts)} 份：{sorted(seen_ts)[:1]}～{sorted(seen_ts)[-1:]}")
    return out


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--panel-start", default="2009-01-01")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    snaps = load_components(args.refresh)
    print(f"成分快照 {len(snaps)} 行（{snaps[0][0]}～{snaps[-1][0]}）")
    intervals = [r for r in snapshots_to_intervals(snaps) if not r["to"] or r["to"] >= args.panel_start]
    print(f"{args.panel_start} 后有效的成员区间 {len(intervals)} 个，代码 {len({r['ticker'] for r in intervals})} 个")

    wiki, sec, oi = wiki_ciks(args.refresh), sec_ticker_map(args.refresh), oi150_map()
    wb = wayback_maps(args.refresh)
    print(f"解析源：维基 {len(wiki)}、SEC 现行 {len(sec)}、Wayback {len(wb)}、OI-150 {len(oi)}、覆盖表 {len(overrides())}")
    subs = Submissions(args.refresh)
    ovr = overrides()
    today = date.today().isoformat()

    def clip(r: dict) -> tuple[str, str]:
        return max(r["from"], args.panel_start), r["to"] or today

    def layer_candidates(r: dict) -> list[tuple[str, str, bool, tuple[str, str] | None]]:
        """[(来源, cik, 强证据, 日期界)]：强证据 = override，或 Wayback 快照日落在区间内；日期界只有 override 有（该 CIK 只在此界内适用）。"""
        out: list[tuple[str, str, bool, tuple[str, str] | None]] = []
        have: dict[str, int] = {}

        def add(src, cik, strong=False, bounds=None):
            if cik not in have:
                have[cik] = len(out); out.append((src, cik, strong, bounds))
            elif strong and not out[have[cik]][2]:      # 同一 CIK 后到的强证据（快照落在区间内）升级前面的候选
                src0, _, _, b0 = out[have[cik]]
                out[have[cik]] = (src0, cik, True, b0)
        lo, hi = clip(r)
        for o in ovr:
            o_from, o_to = (o.get("from") or "0000-01-01"), (o.get("to") or "9999-12-31")
            if o["ticker"].upper() == r["ticker"] and o_from <= hi and o_to >= lo:
                add("override", cik10(o["cik"]), True, (o_from, o_to))
        for src, m in (("wiki", wiki), ("sec", sec)):
            for cik in m.get(r["ticker"], []):
                add(src, cik)
        lo_x = (date.fromisoformat(lo) - timedelta(days=SPAN_TOL)).isoformat()
        hi_x = (date.fromisoformat(hi) + timedelta(days=SPAN_TOL)).isoformat()
        for cik, snap in wb.get(r["ticker"], []):
            if lo_x <= snap <= hi_x:
                add("wayback", cik, lo <= snap <= hi)
        for cik in oi.get(r["ticker"], []):
            add("oi150", cik)
        return out

    def span_of(cik: str, bounds: tuple[str, str] | None) -> tuple[str, str]:
        first, last = subs.span(cik)
        if bounds and first:
            first, last = max(first, bounds[0]), min(last, bounds[1])
        return first, last

    def plausible(cik: str, lo: str, hi: str, bounds: tuple[str, str] | None = None) -> bool:
        first, last = span_of(cik, bounds)
        return bool(first) and first <= hi and last >= lo

    def verified_by_filing(cik: str, r: dict) -> bool:
        lo, hi = clip(r)
        hi = (date.fromisoformat(hi) + timedelta(days=SPAN_TOL)).isoformat()
        return any(ticker_match(r["ticker"], f) for f in subs.instance_tickers(cik, lo, hi, target=r["ticker"]))

    def accept(src: str, cik: str, strong: bool, r: dict, bounds: tuple[str, str] | None = None) -> bool:
        """区间对该候选的接受规则：开放区间的现行代码源与强证据免核实；已结束区间一律核实（无 XBRL 时按申报区间）；
        rename／efts 另须区间内有公众持股。"""
        lo, hi = clip(r)
        if not plausible(cik, lo, hi, bounds):
            return False
        if strong:
            return True
        if not r["to"] and src in ("wiki", "sec", "wayback"):
            return True
        if hi < XBRL_FROM:
            return src in ("wiki", "sec", "wayback", "oi150")
        if not verified_by_filing(cik, r):
            return False
        if src in ("rename", "efts") and subs.public_float(cik, lo, (date.fromisoformat(hi) + timedelta(days=SPAN_TOL)).isoformat()) <= 0:
            return False
        return True

    def assemble(r: dict, cands: list[tuple[str, str, tuple[str, str] | None]]) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str]]]:
        """候选拼接覆盖裁剪后的区间 → ([(src, cik, seg_from, seg_to)], [未覆盖段])；override 的申报区间按其日期界裁剪。"""
        lo, hi = clip(r)
        spans = [(src, cik, *span_of(cik, bounds)) for src, cik, bounds in cands]
        spans = [x for x in spans if x[2] and x[2] <= x[3]]
        segs: list[tuple[str, str, str, str]] = []
        gaps: list[tuple[str, str]] = []
        cur = date.fromisoformat(lo)
        end = date.fromisoformat(hi)
        while cur <= end:
            ok = [x for x in spans if date.fromisoformat(x[2]) <= cur + timedelta(days=SPAN_TOL) and date.fromisoformat(x[3]) >= cur]
            if not ok:
                later = [date.fromisoformat(x[2]) for x in spans if date.fromisoformat(x[2]) > cur + timedelta(days=SPAN_TOL)]
                if not later:
                    gaps.append((cur.isoformat(), hi)); break
                nxt = min(later)
                gaps.append((cur.isoformat(), (nxt - timedelta(days=1)).isoformat()))
                cur = nxt
                continue
            active = [x for x in ok if date.fromisoformat(x[2]) <= cur]      # 已在申报的优先于 400 天内才开始申报的后继主体
            pool = active or ok
            best_pri = min(PRIORITY[x[0]] for x in pool)
            top = [x for x in pool if PRIORITY[x[0]] == best_pri]
            if len(top) > 1:      # 同级并列（合并申报的母子公司）：取区间内公众持股大者
                top.sort(key=lambda x: (subs.public_float(x[1], lo, hi), x[3]), reverse=True)
            else:
                top.sort(key=lambda x: x[3], reverse=True)
            src, cik, first, last = top[0]
            seg_end = end
            if date.fromisoformat(last) < end - timedelta(days=SPAN_TOL):
                seg_end = max(date.fromisoformat(last), cur)
            later = [date.fromisoformat(x[2]) for x in spans if x[1] != cik and date.fromisoformat(x[2]) > cur + timedelta(days=SPAN_TOL)
                     and PRIORITY[x[0]] <= PRIORITY[src]]
            if later and min(later) - timedelta(days=1) < seg_end:
                seg_end = min(later) - timedelta(days=1)
            assert seg_end >= cur
            segs.append((src, cik, cur.isoformat(), seg_end.isoformat()))
            cur = seg_end + timedelta(days=1)
        return segs, gaps

    # 第一轮：直接层（含核实）
    segments: dict[int, list[tuple[str, str, str, str]]] = {}
    gaps_of: dict[int, list[tuple[str, str]]] = {}
    accepted_of: dict[int, list[tuple[str, str, tuple[str, str] | None]]] = {}
    for i, r in enumerate(intervals):
        acc = [(src, cik, bounds) for src, cik, strong, bounds in layer_candidates(r) if accept(src, cik, strong, r, bounds)]
        accepted_of[i] = acc
        segments[i], gaps_of[i] = assemble(r, acc)
        if i % 100 == 0:
            print(f"  第一轮 {i}/{len(intervals)}", flush=True)
    # 第二轮：改名候选与全文检索候选（须核实）
    by_start: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(intervals):
        by_start[r["from"]].append(i)
    for i, r in enumerate(intervals):
        if not gaps_of[i]:
            continue
        lo, hi = clip(r)
        if hi < XBRL_FROM:
            continue
        extra: list[tuple[str, str]] = []
        known = {c for _, c, _ in accepted_of[i]}
        if r["to"]:
            e = date.fromisoformat(r["to"])
            for k in range(0, 8):
                for j in by_start.get((e + timedelta(days=k)).isoformat(), []):
                    if intervals[j]["ticker"] != r["ticker"]:
                        for _, cik, _, _ in segments.get(j, []):
                            if cik not in known and cik not in {c for _, c in extra}:
                                extra.append(("rename", cik))
        for cik in efts_candidates(r["ticker"], lo, (date.fromisoformat(hi) + timedelta(days=SPAN_TOL)).isoformat(), args.refresh):
            if cik not in known and cik not in {c for _, c in extra}:
                extra.append(("efts", cik))
        verified = [(src, cik, None) for src, cik in extra if accept(src, cik, False, r)]
        if verified:
            accepted_of[i] = accepted_of[i] + verified
            segments[i], gaps_of[i] = assemble(r, accepted_of[i])
        if i % 100 == 0:
            print(f"  第二轮 {i}/{len(intervals)}", flush=True)

    members, panel, audit = [], [], []
    n_fin = n_nocik = n_split = 0
    src_count: Counter = Counter()
    for i, r in enumerate(intervals):
        segs = segments[i]
        if len(segs) > 1:
            n_split += 1
        for src, cik, sf, st in segs:
            info = subs.info(cik); first, last = subs.span(cik)
            rec = {"ticker": r["ticker"], "from": sf, "to": "" if (not r["to"] and st >= today) else st, "cik": cik, "cik_source": src,
                   "name": info["name"], "sic": info["sic"], "current_ticker": info["current_ticker"], "exchange": info["exchange"],
                   "first_filing": first, "last_filing": last, "status": "", "interval_from": r["from"], "interval_to": r["to"]}
            src_count[src] += 1
            sic = int(info["sic"]) if info["sic"].isdigit() else None
            if sic is not None and SIC_FIN[0] <= sic <= SIC_FIN[1]:
                rec["status"] = "financial"; n_fin += 1
            else:
                rec["status"] = "ok" if sic is not None else "ok_sic_missing"
                panel.append({"effective_from": sf, "effective_to": rec["to"], "screen_year": sf[:4], "security_code": cik,
                              "security_name": f"{r['ticker']} {info['name']}".strip(), "avg_roe_3y": "", "rank": ""})
            members.append(rec)
        for a, b in gaps_of[i]:
            n_nocik += 1
            members.append({"ticker": r["ticker"], "from": a, "to": "" if (not r["to"] and b >= today) else b, "cik": "", "cik_source": "", "name": "", "sic": "",
                            "current_ticker": "", "exchange": "", "first_filing": "", "last_filing": "", "status": "no_cik",
                            "interval_from": r["from"], "interval_to": r["to"]})
            audit.append({"ticker": r["ticker"], "from": a, "to": b, "issue": "no_cik",
                          "detail": ";".join(f"{s}:{c}:{subs.span(c)[0]}~{subs.span(c)[1]}" for s, c, _, _ in layer_candidates(r))})

    price_override = {(o["ticker"].upper(), cik10(o["cik"])): (o.get("price_ticker") or "").upper() for o in ovr}
    for m in members:
        m["price_ticker"] = price_override.get((m["ticker"], m["cik"]), "") if m["cik"] else ""
    member_fields = ["ticker", "from", "to", "cik", "cik_source", "name", "sic", "current_ticker", "exchange", "first_filing",
                     "last_filing", "status", "interval_from", "interval_to", "price_ticker"]
    for path, rows, fields in ((MEMBERS_OUT, members, member_fields),
                               (PANEL_OUT, sorted(panel, key=lambda x: (x["security_code"], x["effective_from"])),
                                ["effective_from", "effective_to", "screen_year", "security_code", "security_name", "avg_roe_3y", "rank"]),
                               (AUDIT_OUT, audit, ["ticker", "from", "to", "issue", "detail"])):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n"); w.writeheader(); w.writerows(rows)
    codes = {p["security_code"] for p in panel}
    days_tot = days_bad = 0
    for m in members:
        a = max(date.fromisoformat(m["from"]), date(2012, 5, 1)); b = date.fromisoformat(m["to"]) if m["to"] else date.today()
        d = max((b - a).days, 0); days_tot += d
        if m["status"] == "no_cik":
            days_bad += d
    print(f"解析来源 {dict(src_count)}；拆段 {n_split}；未解析段 {n_nocik}（2012-05 起成员·日 {days_bad / max(days_tot, 1):.1%}）；"
          f"金融剔除 {n_fin}；面板区间 {len(panel)}、公司 {len(codes)}")
    print(f"→ {PANEL_OUT}\n→ {MEMBERS_OUT}\n→ {AUDIT_OUT}（{len(audit)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

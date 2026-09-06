#!/usr/bin/env python3
"""OI-159：美股历史成分的未复权日线与公司行动（Yahoo ＋ Tiingo 免费档两源合一）。

预登记：`docs/reports/us_sp500_backtest_prereg.zh.md` §2「价格与公司行动」。

取价规则（逐 CIK 一份价格文件，`security_code` = 10 位 CIK）：
  1. 有现行代码（submissions `tickers`）→ Yahoo `v8/finance/chart`（`events=div,splits`）；Yahoo 的收盘与分红额按其后拆股
     还原为未复权（收盘 × Π 其后拆股比，分红同式）。
  2. 无现行代码、或 Yahoo 序列首日晚于最早成员区间起点 30 天以上（代码复用／再上市）→ Tiingo 免费档按历史代码取
     （token 读 `TIINGO_TOKEN` 或 `~/.config/raykey/tiingo_token`；50 请求/小时，逐请求间隔 73 秒；`close`／`divCash`／`splitFactor` 原生未复权）。
  3. 每个成员区间按序列覆盖判 ok／partial／no_price（首日 ≤ 区间起 + 30 天且末日 ≥ 区间止 − 7 天）。
原始响应缓存 `raw/prices/{yahoo,tiingo}/<代码>.json`，已有即跳过（`--refresh` 重取）；两源都失败的区间记 no_price。

输出：
  data/raw/ohlcv_us/<CIK>.csv                       date,open,close,high,low,volume（未复权，与 A 股同列）
  data/raw/ohlcv_us/INDEX_SP500TR.csv               标普 500 全收益（Yahoo ^SP500TR），只进 summary
  data/raw/ohlcv_us/price_index.csv                 逐 CIK：所用代码、来源、首末日、根数、分红与拆股数
  data/raw/corporate_actions/us_corporate_actions.csv   A 股事件表同列：现金红利 → cash_per_share；拆股 k:1 → share_ratio = k − 1
  data/raw/us_delisted_roster.csv                   security_code,last_trade_date（序列末日早于今日 10 天者）
  data/interim/us_price_coverage.csv                逐成员区间的覆盖状态
用法：
    python3 scripts/fetch_us_ohlcv_history.py [--phase yahoo|tiingo|all] [--only CIK,CIK] [--refresh]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/experiments/exp_us_sp500_port/raw/prices"
MEMBERS = ROOT / "data/processed/us_sp500_members.csv"
OHLCV = ROOT / "data/raw/ohlcv_us"
ACTIONS = ROOT / "data/raw/corporate_actions/us_corporate_actions.csv"
ROSTER = ROOT / "data/raw/us_delisted_roster.csv"
COVERAGE = ROOT / "data/interim/us_price_coverage.csv"
WEB_HDR = {"User-Agent": "Mozilla/5.0"}
START_TOL, END_TOL = 30, 7
TIINGO_GAP = 73.0          # 秒：免费档 50 请求/小时
OHLCV_FIELDS = ["date", "open", "close", "high", "low", "volume"]
ACTION_FIELDS = ["security_code", "security_name", "ex_dividend_date", "cash_per_share", "share_ratio", "plan",
                 "report_date", "plan_notice_date", "progress", "rights_ratio", "rights_price"]


def tiingo_token() -> str:
    tok = os.environ.get("TIINGO_TOKEN", "").strip()
    if not tok:
        p = Path.home() / ".config/raykey/tiingo_token"
        tok = p.read_text().strip() if p.exists() else ""
    if not tok:
        sys.exit("缺 Tiingo token：设 TIINGO_TOKEN 或写入 ~/.config/raykey/tiingo_token")
    return tok


def ysym(t: str) -> str:
    return t.replace(".", "-")


def _get(url: str, timeout: int = 60) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=WEB_HDR), timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:  # noqa: BLE001
        return -1, b""


# ------------------------------------------------------------------ Yahoo
def yahoo_fetch(sym: str, refresh: bool) -> dict | None:
    path = RAW / "yahoo" / f"{sym}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?period1=0&period2={int(time.time())}"
           f"&interval=1d&events=div%2Csplits")
    for attempt in range(4):
        code, body = _get(url)
        if code == 200:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            time.sleep(0.6)
            return json.loads(body)
        if code == 404:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"http": 404}))
            return {"http": 404}
        time.sleep(30 * (attempt + 1))
    return None


def yahoo_series(d: dict) -> tuple[list[dict], list[tuple[str, float]], list[tuple[str, float]]]:
    """→ (未复权日线, 分红事件[(除息日, 每股现金)], 拆股事件[(日, 比)])。Yahoo 价与分红额已按其后拆股折算，此处还原。"""
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        return [], [], []
    r = res[0]
    off = int((r.get("meta") or {}).get("gmtoffset") or 0)

    def day(ts: int) -> str:
        return datetime.fromtimestamp(int(ts) + off, tz=timezone.utc).date().isoformat()

    ev = r.get("events") or {}
    splits = sorted((day(v["date"]), float(v["numerator"]) / float(v["denominator"])) for v in (ev.get("splits") or {}).values()
                    if float(v.get("denominator") or 0) > 0 and float(v.get("numerator") or 0) > 0)

    def factor(dday: str) -> float:
        f = 1.0
        for sd, ratio in splits:
            if sd > dday:
                f *= ratio
        return f

    q = (r.get("indicators") or {}).get("quote") or [{}]
    q = q[0]
    bars = []
    for i, ts in enumerate(r.get("timestamp") or []):
        c = (q.get("close") or [None])[i] if i < len(q.get("close") or []) else None
        if c is None:
            continue
        dd = day(ts); f = factor(dd)
        def v(k):
            x = (q.get(k) or [None])[i] if i < len(q.get(k) or []) else None
            return x
        o, h, l, vol = v("open"), v("high"), v("low"), v("volume")
        bars.append({"date": dd, "open": f"{(o if o is not None else c) * f:.4f}", "close": f"{c * f:.4f}",
                     "high": f"{(h if h is not None else c) * f:.4f}", "low": f"{(l if l is not None else c) * f:.4f}",
                     "volume": f"{(vol or 0) / f:.0f}"})
    bars.sort(key=lambda b: b["date"])
    divs = sorted((day(v["date"]), float(v["amount"]) * factor(day(v["date"]))) for v in (ev.get("dividends") or {}).values() if v.get("amount"))
    return bars, divs, splits


# ------------------------------------------------------------------ Tiingo
class Tiingo:
    def __init__(self, token: str):
        self.token = token
        self.last = 0.0

    def fetch(self, sym: str, refresh: bool) -> list | None:
        path = RAW / "tiingo" / f"{sym}.json"
        if path.exists() and not refresh:
            return json.loads(path.read_text())
        url = (f"https://api.tiingo.com/tiingo/daily/{sym}/prices?startDate=1980-01-01&endDate={date.today().isoformat()}"
               f"&format=json&token={self.token}")
        for attempt in range(5):
            wait = TIINGO_GAP - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            code, body = _get(url, timeout=120)
            self.last = time.time()
            if code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                return json.loads(body)
            if code == 404:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]")
                return []
            print(f"  tiingo {sym} HTTP {code}，退避 {600 * (attempt + 1)} 秒", flush=True)
            time.sleep(600 * (attempt + 1))
        return None


def tiingo_series(rows: list) -> tuple[list[dict], list[tuple[str, float]], list[tuple[str, float]]]:
    bars, divs, splits = [], [], []
    for r in rows:
        dd = str(r.get("date", ""))[:10]
        c = r.get("close")
        if not dd or c is None:
            continue
        bars.append({"date": dd, "open": f"{r.get('open') if r.get('open') is not None else c:.4f}", "close": f"{c:.4f}",
                     "high": f"{r.get('high') if r.get('high') is not None else c:.4f}", "low": f"{r.get('low') if r.get('low') is not None else c:.4f}",
                     "volume": f"{r.get('volume') or 0:.0f}"})
        if r.get("divCash"):
            divs.append((dd, float(r["divCash"])))
        sf = float(r.get("splitFactor") or 1.0)
        if abs(sf - 1.0) > 1e-6:
            splits.append((dd, sf))
    bars.sort(key=lambda b: b["date"])
    return bars, sorted(divs), sorted(splits)


# ------------------------------------------------------------------ 覆盖判定与输出
def coverage(bars: list[dict], start: str, end: str) -> str:
    if not bars:
        return "no_price"
    first, last = bars[0]["date"], bars[-1]["date"]
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else date.today() - timedelta(days=7)
    ok_start = date.fromisoformat(first) <= s + timedelta(days=START_TOL)
    ok_end = date.fromisoformat(last) >= e - timedelta(days=END_TOL)
    if ok_start and ok_end:
        return "ok"
    if date.fromisoformat(first) <= e and date.fromisoformat(last) >= s:
        return "partial"
    return "no_price"


def write_ohlcv(cik: str, bars: list[dict]) -> None:
    OHLCV.mkdir(parents=True, exist_ok=True)
    with (OHLCV / f"{cik}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OHLCV_FIELDS, lineterminator="\n"); w.writeheader(); w.writerows(bars)


def fetch_index(refresh: bool) -> None:
    d = yahoo_fetch("%5ESP500TR", refresh)
    if not d or d.get("http") == 404:
        print("  ^SP500TR 取数失败", file=sys.stderr); return
    bars, _, _ = yahoo_series(d)
    with (OHLCV / "INDEX_SP500TR.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OHLCV_FIELDS, lineterminator="\n"); w.writeheader(); w.writerows(bars)
    print(f"  ^SP500TR {len(bars)} 根（{bars[0]['date']}～{bars[-1]['date']}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("yahoo", "tiingo", "all"), default="all")
    ap.add_argument("--only", default="", help="只处理这些代码（ticker），逗号分隔")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    members = [r for r in csv.DictReader(MEMBERS.open(encoding="utf-8")) if r["cik"] and r["status"] in ("ok", "ok_sic_missing")]
    only = set(args.only.split(",")) if args.only else None
    if only:
        members = [r for r in members if r["ticker"] in only]
    OHLCV.mkdir(parents=True, exist_ok=True)
    fetch_index(args.refresh)

    # 逐代码取序列：先 Yahoo（现行上市代码），区间覆盖不全的再 Tiingo（历史代码）；每个成员段记所用序列
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in members:
        by_ticker[r["ticker"]].append(r)
    series: dict[str, tuple[str, list[dict], list, list]] = {}      # ticker → (source, bars, divs, splits)
    seg_status: dict[tuple[str, str, str], tuple[str, str]] = {}     # (ticker, from, to) → (status, series_key)

    def try_assign(ticker: str, key: str, source: str, bars, divs, splits) -> int:
        series[key] = (source, bars, divs, splits)
        n = 0
        for r in by_ticker[ticker]:
            k = (ticker, r["from"], r["to"])
            st = coverage(bars, r["from"], r["to"])
            prev = seg_status.get(k, ("no_price", ""))
            rank = {"ok": 2, "partial": 1, "no_price": 0}
            if rank[st] > rank[prev[0]]:
                seg_status[k] = (st, key)
            n += st == "ok"
        return n

    tickers = sorted(by_ticker)
    if args.phase in ("yahoo", "all"):
        n_y = 0
        for i, t in enumerate(tickers, 1):
            cands = []
            cur = (by_ticker[t][0].get("current_ticker") or "").strip()
            if cur:
                cands.append(cur)
            for r in by_ticker[t]:                       # 覆盖表给的历史取价代码（CSC 之于 DXC）
                pt = (r.get("price_ticker") or "").strip()
                if pt and pt not in cands:
                    cands.append(pt)
            if t not in cands:
                cands.append(t)
            for c in cands:
                d = yahoo_fetch(ysym(c), args.refresh)
                if not d or d.get("http") == 404:
                    continue
                bars, divs, splits = yahoo_series(d)
                if bars:
                    n_y += try_assign(t, f"yahoo:{c}", "yahoo", bars, divs, splits) > 0
                    if all(seg_status.get((t, r["from"], r["to"]), ("",))[0] == "ok" for r in by_ticker[t]):
                        break
            if i % 50 == 0:
                print(f"  yahoo {i}/{len(tickers)}", flush=True)
        print(f"Yahoo 段：{n_y} 个代码至少一段覆盖 ok", flush=True)

    if args.phase in ("tiingo", "all"):
        tg = Tiingo(tiingo_token())
        todo = [t for t in tickers if any(seg_status.get((t, r["from"], r["to"]), ("no_price",))[0] != "ok" for r in by_ticker[t])]
        # Yahoo 段已跑过（--phase tiingo 单独运行时）从缓存重放
        if args.phase == "tiingo":
            for t in tickers:
                cur = (by_ticker[t][0].get("current_ticker") or "").strip()
                for c in ([cur] if cur else []) + ([t] if t != cur else []):
                    path = RAW / "yahoo" / f"{ysym(c)}.json"
                    if path.exists():
                        d = json.loads(path.read_text())
                        if d.get("http") != 404:
                            bars, divs, splits = yahoo_series(d)
                            if bars:
                                try_assign(t, f"yahoo:{c}", "yahoo", bars, divs, splits)
            todo = [t for t in tickers if any(seg_status.get((t, r["from"], r["to"]), ("no_price",))[0] != "ok" for r in by_ticker[t])]
        print(f"Tiingo 段：{len(todo)} 个代码待取（约 {len(todo) * TIINGO_GAP / 3600:.1f} 小时）", flush=True)
        for i, t in enumerate(todo, 1):
            names = [t] + [pt for pt in {(r.get("price_ticker") or "").strip() for r in by_ticker[t]} if pt and pt != t]
            for nm in names:
                rows = tg.fetch(ysym(nm), args.refresh)
                if rows:
                    bars, divs, splits = tiingo_series(rows)
                    if bars:
                        try_assign(t, f"tiingo:{nm}", "tiingo", bars, divs, splits)
                if all(seg_status.get((t, r["from"], r["to"]), ("",))[0] == "ok" for r in by_ticker[t]):
                    break
            if i % 10 == 0:
                print(f"  tiingo {i}/{len(todo)}", flush=True)

    # ---- 逐 CIK 写价格文件：并入该 CIK 各段所用序列（段前留 400 天给均线热身），同日取先到者
    by_cik: dict[str, list[dict]] = defaultdict(list)
    for r in members:
        by_cik[r["cik"]].append(r)
    index_rows, actions, cov_rows = [], {}, []
    for cik in sorted(by_cik):
        merged: dict[str, dict] = {}
        used: list[str] = []
        divs_all: dict[str, float] = {}
        splits_all: dict[str, float] = {}
        for r in by_cik[cik]:
            k = (r["ticker"], r["from"], r["to"])
            st, key = seg_status.get(k, ("no_price", ""))
            cov_rows.append({"ticker": r["ticker"], "from": r["from"], "to": r["to"], "cik": cik, "series": key, "status": st})
            if not key:
                continue
            src, bars, divs, splits = series[key]
            lo = (date.fromisoformat(r["from"]) - timedelta(days=400)).isoformat()
            hi = (date.fromisoformat(r["to"]) + timedelta(days=60)).isoformat() if r["to"] else "9999-12-31"
            for b in bars:
                if lo <= b["date"] <= hi and b["date"] not in merged:
                    merged[b["date"]] = b
            for d, amt in divs:
                if lo <= d <= hi:
                    divs_all[d] = amt
            for d, ratio in splits:
                if lo <= d <= hi:
                    splits_all[d] = ratio
            if key not in used:
                used.append(key)
        if not merged:
            continue
        bars = [merged[d] for d in sorted(merged)]
        write_ohlcv(cik, bars)
        index_rows.append({"cik": cik, "series": "|".join(used), "first_date": bars[0]["date"], "last_date": bars[-1]["date"],
                           "n_bars": str(len(bars)), "n_div": str(len(divs_all)), "n_split": str(len(splits_all))})
        name = by_cik[cik][0]["ticker"]
        rows = [{"security_code": cik, "security_name": name, "ex_dividend_date": d, "cash_per_share": f"{amt:.6f}", "share_ratio": "",
                 "plan": "cash dividend", "report_date": "", "plan_notice_date": "", "progress": "", "rights_ratio": "", "rights_price": ""}
                for d, amt in sorted(divs_all.items()) if amt > 0]
        rows += [{"security_code": cik, "security_name": name, "ex_dividend_date": d, "cash_per_share": "", "share_ratio": f"{ratio - 1:.6f}",
                  "plan": f"split {ratio:g}:1", "report_date": "", "plan_notice_date": "", "progress": "", "rights_ratio": "", "rights_price": ""}
                 for d, ratio in sorted(splits_all.items()) if ratio > 0 and abs(ratio - 1) > 1e-6]
        actions[cik] = rows

    with (OHLCV / "price_index.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["cik", "series", "first_date", "last_date", "n_bars", "n_div", "n_split"], lineterminator="\n")
        w.writeheader(); w.writerows(index_rows)
    COVERAGE.parent.mkdir(parents=True, exist_ok=True)
    with COVERAGE.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["ticker", "from", "to", "cik", "series", "status"], lineterminator="\n"); w.writeheader(); w.writerows(cov_rows)
    cutoff = (date.today() - timedelta(days=10)).isoformat()
    roster = [{"security_code": r["cik"], "last_trade_date": r["last_date"]} for r in index_rows if r["last_date"] < cutoff]
    with ROSTER.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["security_code", "last_trade_date"], lineterminator="\n"); w.writeheader(); w.writerows(roster)
    ACTIONS.parent.mkdir(parents=True, exist_ok=True)
    with ACTIONS.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ACTION_FIELDS, lineterminator="\n"); w.writeheader()
        for c in sorted(actions):
            w.writerows(sorted(actions[c], key=lambda x: x["ex_dividend_date"]))
    from collections import Counter
    st = Counter(r["status"] for r in cov_rows)
    days_tot = days_bad = 0
    for r in cov_rows:
        s = max(date.fromisoformat(r["from"]), date(2012, 5, 1)); e = date.fromisoformat(r["to"]) if r["to"] else date.today()
        d = max((e - s).days, 0); days_tot += d
        if r["status"] != "ok":
            days_bad += d
    print(f"成员段覆盖 {dict(st)}；2012-05 起非 ok 成员·日占比 {days_bad / max(days_tot, 1):.1%}；价格文件 {len(index_rows)}；"
          f"退市名册 {len(roster)}；事件 {sum(len(v) for v in actions.values())} 条 → {ACTIONS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

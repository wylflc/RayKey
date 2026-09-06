#!/usr/bin/env python3
"""标普 100 历史成分面板（OI-159 追加读数：股票池缩小为标普 100）。

成分来源：英文 Wikipedia「S&P 100」页面的修订历史（MediaWiki API）。每月取月初前最后一个修订版解析成分表；
相邻两月成分有差异时再取该月内全部修订版，把变动定到修订日（S&P 公告后数日内的编辑）。
代码 → CIK 不另解析：标普 100 ⊂ 标普 500，直接按 `data/processed/us_sp500_members.csv` 的（代码，区间）重叠取 CIK，
金融股（members 状态 `financial`）与 `no_cik` 段按标普 500 面板同样处理（剔除／计入未解析）。

产物：
  data/processed/pit_attention/panel_sp100_us.csv   与 panel_sp500_us.csv 同列
  data/interim/us_sp100_panel_audit.csv             逐区间映射结果（mapped / financial / unmapped / 快照弃用）
原始修订内容缓存在 data/experiments/exp_us_sp500_port/raw/wiki_sp100/（不入库）。
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
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_us_index_panel import snapshots_to_intervals  # noqa: E402

API = "https://en.wikipedia.org/w/api.php"
TITLE = "S&P 100"
HDR = {"User-Agent": "RayKey research (contact: wzq9464@gmail.com)", "Accept-Encoding": "identity"}
RAW = ROOT / "data/experiments/exp_us_sp500_port/raw/wiki_sp100"
MEMBERS = ROOT / "data/processed/us_sp500_members.csv"
PANEL_OUT = ROOT / "data/processed/pit_attention/panel_sp100_us.csv"
AUDIT_OUT = ROOT / "data/interim/us_sp100_panel_audit.csv"
TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
# 标普 500 成员表按后来的代码登记同一主体，标普 100 页面用当年代码：直接查不到时按别名再查
ALIASES = {"AA": "ARNC", "BHI": "BHGE", "KFT": "MDLZ", "PCLN": "BKNG", "WAG": "WBA"}


def api(params: dict, retries: int = 4) -> dict:
    q = urllib.parse.urlencode({**params, "format": "json"})
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{API}?{q}", headers=HDR), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"API {q[:80]}: {last}")


def revision_list(start: str, refresh: bool) -> list[tuple[int, str]]:
    """[(revid, timestamp)] 升序，自 start 前最后一个修订版起。"""
    path = RAW / "revisions.json"
    if path.exists() and not refresh:
        return [tuple(x) for x in json.loads(path.read_text())]
    revs: list[tuple[int, str]] = []
    params = {"action": "query", "prop": "revisions", "titles": TITLE, "rvprop": "ids|timestamp",
              "rvlimit": "max", "rvdir": "newer", "rvstart": f"{start}T00:00:00Z"}
    cont: dict = {}
    while True:
        d = api({**params, **cont})
        page = next(iter(d["query"]["pages"].values()))
        revs += [(r["revid"], r["timestamp"]) for r in page.get("revisions", [])]
        if "continue" not in d:
            break
        cont = d["continue"]
        time.sleep(0.3)
    # start 前的最后一个修订版（月初快照的基线）
    d = api({"action": "query", "prop": "revisions", "titles": TITLE, "rvprop": "ids|timestamp", "rvlimit": 1,
             "rvdir": "older", "rvstart": f"{start}T00:00:00Z"})
    page = next(iter(d["query"]["pages"].values()))
    for r in page.get("revisions", []):
        revs.insert(0, (r["revid"], r["timestamp"]))
    revs.sort(key=lambda x: x[1])
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(revs))
    return revs


def revision_text(revid: int) -> str | None:
    path = RAW / f"rev_{revid}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    d = api({"action": "query", "prop": "revisions", "revids": str(revid), "rvprop": "content", "rvslots": "main"})
    page = next(iter(d["query"]["pages"].values()))
    revs = page.get("revisions") or []
    if not revs:
        return None
    slot = revs[0].get("slots", {}).get("main", {})
    txt = slot.get("*") or slot.get("content") or ""
    path.write_text(txt, encoding="utf-8")
    time.sleep(0.5)
    return txt


def _cell_text(cell: str) -> str:
    s = cell.strip()
    s = re.sub(r"\{\{\s*(?:nyse|nasdaq|NYSE|NASDAQ|Nyse|Nasdaq)\s*\|\s*([^}|]+)(?:\|[^}]*)?\}\}", r"\1", s)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "").strip()
    s = s.split(":")[-1].strip()          # NYSE:AAPL → AAPL
    return s.upper().replace("-", ".").replace("−", ".")


def parse_components(txt: str) -> set[str] | None:
    """取第一个表头含 Symbol／Ticker 的 wikitable 的首列代码。"""
    for m in re.finditer(r"\{\|[^\n]*\n(.*?)\n\|\}", txt, flags=re.S):
        body = m.group(1)
        head = body[:400]
        if not re.search(r"!\s*(Symbol|Ticker)", head, flags=re.I):
            continue
        out: set[str] = set()
        for row in re.split(r"\n\|-[^\n]*\n", "\n" + body):
            cells = [c for c in re.split(r"\n\|\s?|\|\|", "\n" + row) if c.strip() and not c.strip().startswith("!")]
            if not cells:
                continue
            tok = _cell_text(cells[0])
            if TICKER_RE.match(tok):
                out.add(tok)
        return out
    return None


def month_starts(start: str, end: str) -> list[str]:
    d = date.fromisoformat(start).replace(day=1)
    out = []
    while d <= date.fromisoformat(end):
        out.append(d.isoformat())
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2011-11-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--months-limit", type=int, default=0, help="冒烟：只处理前 N 个月")
    ap.add_argument("--max-refine", type=int, default=20, help="月内有变动时最多取多少个月内修订版")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    revs = revision_list(args.start, args.refresh)
    print(f"修订版 {len(revs)} 个：{revs[0][1][:10]}～{revs[-1][1][:10]}")
    months = month_starts(args.start, args.end)
    if args.months_limit:
        months = months[: args.months_limit]

    snaps: list[tuple[str, set[str]]] = []
    dropped: list[dict] = []
    prev_ok: set[str] | None = None

    def snapshot(revid: int, ts: str) -> set[str] | None:
        nonlocal prev_ok
        txt = revision_text(revid)
        comps = parse_components(txt) if txt else None
        reason = ""
        if comps is None:
            reason = "no_table"
        elif not 90 <= len(comps) <= 110:
            reason = f"count_{len(comps)}"
        elif prev_ok is not None and len(comps ^ prev_ok) > 15:
            reason = f"jump_{len(comps ^ prev_ok)}"
        if reason:
            dropped.append({"revid": revid, "timestamp": ts, "reason": reason})
            return None
        prev_ok = comps
        return comps

    # 月初快照：月初前最后一个修订版
    picked: list[tuple[int, str]] = []
    for mstart in months:
        cands = [r for r in revs if r[1][:10] < mstart]
        if not cands:
            continue
        r = cands[-1]
        if not picked or picked[-1][0] != r[0]:
            picked.append(r)
    last_members: set[str] | None = None
    last_rev: tuple[int, str] | None = None
    for revid, ts in picked:
        comps = snapshot(revid, ts)
        if comps is None:
            continue
        if last_members is not None and comps != last_members and last_rev is not None:
            # 月内定日：取两快照之间的全部修订版（上限 max-refine，超出则等距抽样）
            between = [r for r in revs if last_rev[1] < r[1] < ts]
            if len(between) > args.max_refine:
                step = len(between) / args.max_refine
                between = [between[int(i * step)] for i in range(args.max_refine)]
            for rid, rts in between:
                c2 = snapshot(rid, rts)
                if c2 is not None:
                    snaps.append((rts[:10], c2))
        snaps.append((ts[:10], comps))
        last_members, last_rev = comps, (revid, ts)
    # 同日多快照取最后一个；首个快照日期改为 start（基线）
    by_day: dict[str, set[str]] = {}
    for d, s in snaps:
        by_day[d] = s
    snaps = sorted(by_day.items())
    if snaps and snaps[0][0] < args.start:
        snaps[0] = (args.start, snaps[0][1])
    print(f"快照 {len(snaps)} 份（弃用 {len(dropped)}：{[x['reason'] for x in dropped][:8]}）")
    intervals = snapshots_to_intervals(snaps)
    print(f"成分区间 {len(intervals)} 个，代码 {len({r['ticker'] for r in intervals})} 个")

    # 代码 → CIK：按标普 500 成员表重叠
    members = list(csv.DictReader(MEMBERS.open(encoding="utf-8")))
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for m in members:
        by_ticker[m["ticker"].upper().replace("-", ".")].append(m)
        if m.get("current_ticker"):
            by_ticker[m["current_ticker"].upper().replace("-", ".")].append(m)
    end_default = args.end
    panel: list[dict] = []
    audit: list[dict] = []
    for r in intervals:
        lo, hi = r["from"], r["to"] or end_default
        hits = []
        keys = [r["ticker"]] + ([ALIASES[r["ticker"]]] if r["ticker"] in ALIASES else [])
        for m in [x for k in keys for x in by_ticker.get(k, [])]:
            mlo, mhi = m["from"], m["to"] or end_default
            a, b = max(lo, mlo), min(hi, mhi)
            if a <= b:
                hits.append((m, a, b))
        # 同一 CIK 只留一次（ticker 与 current_ticker 可能重复命中）
        seen = set()
        for m, a, b in sorted(hits, key=lambda x: x[1]):
            key = (m["cik"], a, b)
            if key in seen:
                continue
            seen.add(key)
            status = "financial" if m["status"] == "financial" else ("unmapped" if m["status"] == "no_cik" or not m["cik"] else "mapped")
            audit.append({"ticker": r["ticker"], "from": a, "to": "" if (b == end_default and not r["to"] and not m["to"]) else b,
                          "cik": m["cik"], "name": m["name"], "status": status})
            if status == "mapped":
                to = "" if (b == end_default and not r["to"] and not m["to"]) else b
                panel.append({"effective_from": a, "effective_to": to, "screen_year": a[:4], "security_code": m["cik"],
                              "security_name": f"{m['ticker']} {m['name']}", "avg_roe_3y": "", "rank": ""})
        if not hits:
            audit.append({"ticker": r["ticker"], "from": lo, "to": r["to"], "cik": "", "name": "", "status": "unmapped"})
    for x in dropped:
        audit.append({"ticker": "", "from": x["timestamp"][:10], "to": "", "cik": str(x["revid"]), "name": "", "status": f"snapshot_dropped:{x['reason']}"})

    # 逐年成员·日：mapped / financial / unmapped
    tot: dict[int, int] = defaultdict(int)
    cnt: dict[tuple[int, str], int] = defaultdict(int)
    for a in audit:
        if not a["ticker"]:
            continue
        lo = date.fromisoformat(a["from"]); hi = date.fromisoformat(a["to"] or end_default)
        d = lo
        while d <= hi:
            nxt = min(hi, date(d.year, 12, 31)); n = (nxt - d).days + 1
            tot[d.year] += n; cnt[(d.year, a["status"])] += n
            d = nxt + timedelta(days=1)
    print("逐年成员·日占比（mapped / financial / unmapped）：" + "；".join(
        f"{y} {cnt[(y, 'mapped')] / tot[y]:.0%}/{cnt[(y, 'financial')] / tot[y]:.0%}/{cnt[(y, 'unmapped')] / tot[y]:.1%}" for y in sorted(tot)))
    PANEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    with PANEL_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["effective_from", "effective_to", "screen_year", "security_code", "security_name", "avg_roe_3y", "rank"], lineterminator="\n")
        w.writeheader(); w.writerows(sorted(panel, key=lambda x: (x["security_code"], x["effective_from"])))
    AUDIT_OUT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["ticker", "from", "to", "cik", "name", "status"], lineterminator="\n")
        w.writeheader(); w.writerows(audit)
    print(f"面板 {len(panel)} 行 / {len({p['security_code'] for p in panel})} 家 → {PANEL_OUT}\n审计 {len(audit)} 行 → {AUDIT_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""前期会计差错更正与追溯重述公告的检测（§6.3 第 2 条、§7.4，OI-203）。

供应商在公司更正后原位改写季报与年报行、公告日仍挂原日（五粮液 2025 年三份季报于 2026-04-30 更正），
取数存档只能截住本仓库重取时发现的改写。本脚本以公告标题为一手信号：
「会计差错更正／前期差错／追溯调整／追溯重述」公告，与同一公司前后 15 天内的「更新后／更正后／修订版」
定期报告配对，得到受影响的 (代码, 报告期) 与重述日。

    # 一次性回溯（巨潮全文检索，按关键词全市场分页，再按代码清单过滤）
    python3 scripts/scan_restatement_announcements.py --history --since 2009-01-01 --until YYYY-MM-DD
    # 每日取证快照（§9.1 evidence 阶段之后）
    python3 scripts/scan_restatement_announcements.py --snapshot data/interim/daily_announcements_YYYY-MM-DD.json

输出 `data/interim/restatement_announcements.csv`（追加去重）。`roic_inputs.load_restatement_dates` 读取其中
`kind = updated_report` 且同期有更正公告的行：该报告期若无覆盖重述日的重述前版本（取数存档、
`data/reference/panel_restatement_originals.csv`），可得日延后到重述日（§6.3 第 2 条）。
结尾列出受影响而未登记原文版本的 (代码, 报告期)；`--strict` 时有此类行即非零退出。
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/interim/restatement_announcements.csv"
FIELDS = ["security_code", "security_name", "announcement_date", "kind", "report_period", "paired", "title", "url",
          "source", "detected_at_utc"]
CORRECTION = re.compile(r"会计差错更正|前期差错|追溯调整|追溯重述")
UPDATED = re.compile(r"(\d{4})\s*年\s*(第一季度|一季度|第1季度|半年度|中期|第三季度|三季度|第3季度|年度)报告(?!摘要)"
                     r".*?[（(]\s*(更新后|更正后|修订版|修订稿|修订后|更新版|补充后)\s*[)）]")
EXCLUDE = re.compile(r"摘要|英文|English")
PERIOD = {"第一季度": "03-31", "一季度": "03-31", "第1季度": "03-31", "半年度": "06-30", "中期": "06-30",
          "第三季度": "09-30", "三季度": "09-30", "第3季度": "09-30", "年度": "12-31"}
KEYWORDS = ("会计差错更正", "前期差错", "追溯调整", "追溯重述")
PAIR_DAYS = 15
UA = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}


def classify(title: str) -> tuple[str, str] | None:
    """标题 → (kind, 报告期)；无关标题返回 None。"""
    clean = re.sub(r"</?em>", "", title)
    m = UPDATED.search(clean)
    if m and not EXCLUDE.search(clean):
        return "updated_report", f"{m.group(1)}-{PERIOD[m.group(2)]}"
    if CORRECTION.search(clean):
        return "correction", ""
    return None


def beijing_day(announcement: dict) -> str:
    """公告日（北京时间）：优先取链接路径 `finalpage/YYYY-MM-DD/`，缺失时按 Asia/Shanghai 换算时间戳。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", announcement.get("adjunctUrl") or "")
    if m:
        return m.group(1)
    return datetime.fromtimestamp(announcement["announcementTime"] / 1000, tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def cninfo(params: dict) -> dict:
    """巨潮公告检索一页（接口每页至多 30 条，更大的 pageSize 会让分页失效）。"""
    data = urllib.parse.urlencode(dict(pageNum=1, pageSize=30, column="szse", tabName="fulltext", plate="", stock="",
                                       searchkey="", secid="", category="", trade="", seDate="", sortName="",
                                       sortType="", isHLtitle="true") | params).encode()
    for attempt in range(5):
        try:
            req = urllib.request.Request("http://www.cninfo.com.cn/new/hisAnnouncement/query", data=data, headers=UA)
            return json.load(urllib.request.urlopen(req, timeout=40))
        except Exception:                                     # noqa: BLE001 - retried then raised
            if attempt == 4:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(params)


def cninfo_all(params: dict) -> list[dict]:
    """逐页取完一个检索条件的全部公告。接口的 `totalpages` 向下取整（121 条报 4 页），按 `totalAnnouncement` 向上取整翻页。"""
    out, page, pages = [], 1, 1
    while page <= pages:
        res = cninfo(params | {"pageNum": page})
        rows = res.get("announcements") or []
        total = int(res.get("totalAnnouncement") or 0)
        pages = max(-(-total // 30), res.get("totalpages") or 0)
        out += rows
        if not rows:
            break
        page += 1
    seen, unique = set(), []
    for a in out:
        key = a.get("announcementId") or a.get("adjunctUrl")
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def _row(code: str, name: str, day: str, title: str, url: str, source: str) -> dict | None:
    kind = classify(title)
    if kind is None:
        return None
    return dict(security_code=code, security_name=name, announcement_date=day, kind=kind[0], report_period=kind[1],
                title=re.sub(r"</?em>", "", title), url=url, source=source,
                detected_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def history(since: str, until: str, codes: set[str]) -> list[dict]:
    """关键词全市场分页 → 代码过滤 → 每个更正公告前后 PAIR_DAYS 天内查该公司的定期报告更新版。"""
    found: dict[str, dict] = {}
    for key in KEYWORDS:
        for year in range(int(since[:4]), int(until[:4]) + 1):       # 按年切分，单个检索条件不超过接口的翻页上限
            lo, hi = max(since, f"{year}-01-01"), min(until, f"{year}-12-31")
            hits = cninfo_all(dict(searchkey=key, seDate=f"{lo}~{hi}"))
            for a in hits:
                code = (a.get("secCode") or "").zfill(6)
                if code not in codes:
                    continue
                row = _row(code, a.get("secName") or "", beijing_day(a), a.get("announcementTitle") or "",
                           "http://static.cninfo.com.cn/" + (a.get("adjunctUrl") or ""), f"cninfo:{key}")
                if row:
                    found[row["url"]] = row
            print(f"  {key} {year}：全市场 {len(hits)} 条，累计命中 {len(found)} 条", flush=True)
    orgs = {}
    for corr in sorted({(r["security_code"], r["announcement_date"]) for r in found.values() if r["kind"] == "correction"}):
        code, day = corr
        d0 = date.fromisoformat(day)
        window = f"{d0 - timedelta(days=PAIR_DAYS)}~{d0 + timedelta(days=PAIR_DAYS)}"
        if code not in orgs:
            hits = json.loads(urllib.request.urlopen(urllib.request.Request(
                "http://www.cninfo.com.cn/new/information/topSearch/query",
                data=urllib.parse.urlencode(dict(keyWord=code, maxNum=5)).encode(), headers=UA), timeout=40).read())
            orgs[code] = next((h["orgId"] for h in hits if h.get("code") == code), None)
        if orgs[code] is None:
            continue
        for a in cninfo_all(dict(stock=f"{code},{orgs[code]}", seDate=window)):
            row = _row(code, a.get("secName") or "", beijing_day(a), a.get("announcementTitle") or "",
                       "http://static.cninfo.com.cn/" + (a.get("adjunctUrl") or ""), "cninfo:pairing")
            if row and row["kind"] == "updated_report":
                found[row["url"]] = row
    return list(found.values())


def snapshot(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for a in data.get("announcements") or []:
        day = (a.get("notice_date") or "")[:10]
        for c in a.get("codes") or []:
            row = _row((c.get("stock_code") or "").zfill(6), c.get("short_name") or "", day, a.get("title_ch") or a.get("title") or "",
                       f"https://data.eastmoney.com/notices/detail/{c.get('stock_code')}/{a.get('art_code')}.html",
                       f"eastmoney:{path.name}")
            if row:
                out.append(row)
    return out


def pair(rows: list[dict]) -> None:
    """定期报告更新版与同一公司 PAIR_DAYS 天内的更正公告配对（`paired` = 1）；更正公告自身按是否找到更新版标记。"""
    corrections: dict[str, list[date]] = {}
    for r in rows:
        if r["kind"] == "correction":
            corrections.setdefault(r["security_code"], []).append(date.fromisoformat(r["announcement_date"]))
    updates: dict[str, list[date]] = {}
    for r in rows:
        if r["kind"] == "updated_report":
            d = date.fromisoformat(r["announcement_date"])
            ok = any(abs((d - c).days) <= PAIR_DAYS for c in corrections.get(r["security_code"], []))
            r["paired"] = "1" if ok else "0"
            if ok:
                updates.setdefault(r["security_code"], []).append(d)
    for r in rows:
        if r["kind"] == "correction":
            d = date.fromisoformat(r["announcement_date"])
            r["paired"] = "1" if any(abs((d - u).days) <= PAIR_DAYS for u in updates.get(r["security_code"], [])) else "0"


def load(path: Path = OUT) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def save(rows: list[dict]) -> None:
    merged = {r["url"]: r for r in load() + rows}
    all_rows = sorted(merged.values(), key=lambda r: (r["security_code"], r["announcement_date"], r["kind"], r["report_period"]))
    pair(all_rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)


def unresolved(codes: set[str] | None = None) -> list[tuple[str, str, str]]:
    """受影响的 (代码, 报告期, 重述日) 中没有覆盖该日重述前版本的。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import restatement_archive
    covered: set[tuple[str, str]] = set()
    for ref in restatement_archive.load_filing_originals():
        covered.add((ref["security_code"].zfill(6), ref["report_date"][:10], ref["superseded_at"][:10]))
    for path in sorted((ROOT / "data/raw/financials/superseded").glob("*.csv")):
        for arch in restatement_archive.load_archive(path):
            covered.add(((arch.get("security_code") or "").zfill(6), (arch.get("report_date") or path.stem)[:10],
                         (arch.get("superseded_at") or "")[:10]))
    for kind in ("balance", "income", "cashflow"):
        for arch in restatement_archive.load_archive(ROOT / "data/raw/financials_statements/superseded" / f"{kind}.csv"):
            covered.add(((arch.get("security_code") or "").zfill(6), (arch.get("REPORT_DATE") or "")[:10],
                         (arch.get("superseded_at") or "")[:10]))
    out = []
    for r in load():
        if r["kind"] != "updated_report" or r.get("paired") != "1" or (codes and r["security_code"] not in codes):
            continue
        key = (r["security_code"], r["report_period"])
        if not any(c[:2] == key and c[2] >= r["announcement_date"] for c in covered):
            out.append((r["security_code"], r["report_period"], r["announcement_date"]))
    return sorted(set(out))


def default_codes() -> set[str]:
    codes: set[str] = set()
    for rel in ("data/processed/a_share_core_valuation_pool.csv", "data/processed/a_share_holdings.csv",
                "data/processed/pit_attention/panel_moat_bank_v6b.csv"):
        path = ROOT / rel
        if path.exists():
            with path.open(newline="", encoding="utf-8-sig") as handle:
                codes.update((r.get("security_code") or "").zfill(6) for r in csv.DictReader(handle))
    codes.discard("000000")
    return codes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--since", default="2009-01-01")
    parser.add_argument("--until", default=date.today().isoformat())
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--codes-file", type=Path, help="每行一个代码；缺省 = 核心池 ∪ 持仓 ∪ 回测面板")
    parser.add_argument("--strict", action="store_true", help="受影响而未登记原文版本时非零退出")
    args = parser.parse_args()
    codes = ({c.strip().zfill(6) for c in args.codes_file.read_text().split() if c.strip()} if args.codes_file
             else default_codes())
    rows: list[dict] = []
    if args.history:
        rows += history(args.since, args.until, codes)
    if args.snapshot:
        rows += [r for r in snapshot(args.snapshot) if r["security_code"] in codes]
    if rows:
        save(rows)
    current = load()
    print(f"重述公告台账 {len(current)} 条（更正 {sum(r['kind'] == 'correction' for r in current)}、"
          f"定期报告更新版 {sum(r['kind'] == 'updated_report' for r in current)}，配对 "
          f"{sum(r['kind'] == 'updated_report' and r.get('paired') == '1' for r in current)}）；本次新增候选 {len(rows)}")
    todo = unresolved(codes)
    for code, period, day in todo:
        print(f"  ⚠ {code} {period}：{day} 重述，无原文登记版本 → 可得日按 §6.3 第 2 条延后到重述日；"
              f"如需保留原值，登记 data/reference/panel_restatement_originals.csv")
    if not todo:
        print("受影响报告期均已有覆盖重述日的版本")
    lone = sorted({(r["security_code"], r["security_name"], r["announcement_date"]) for r in current
                   if r["kind"] == "correction" and r.get("paired") != "1" and r["security_code"] in codes})
    if lone:
        print(f"更正公告未找到同期定期报告更新版 {len(lone)} 起（受影响报告期须按公告核对，必要时登记原文版本）：")
        for code, name, day in lone[-20:]:
            print(f"  · {code} {name} {day}")
    return 1 if (args.strict and todo) else 0


if __name__ == "__main__":
    sys.exit(main())

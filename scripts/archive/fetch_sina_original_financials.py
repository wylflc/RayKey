#!/usr/bin/env python3
"""取**原始披露口径**财务指标（新浪财务指标页）——修复东财的追溯重述污染。

为什么需要它
------------
东财两个接口给的都是**当前口径**，含追溯重述。判例康得新（002450）2016 年报：
当年披露营收 92.3 亿 / 归母净利 +19.6 亿 / EPS ~0.55，**东财现值为 28.69 亿 / −17.55 亿 / −0.53**。
用重述值判 2016 年的它，它会显得不值得关注 → 判定不收 → 回测不买 → **那笔亏损永远不会发生**，
幸存者偏差换个入口回来（见 `docs/archive/Ashare_pit_judgment_protocol.md` §7.2）。

新浪按年归档、**不追溯重述**：同一期该页给出 EPS = 0.5569，与当年披露一致。

口径警告（务必先读）
--------------------
**本文件的数与东财的数不可直接混用**，两处定义不同：

* 东财 `basic_eps` = 基本每股收益（**加权平均股数**）；新浪「摊薄每股收益」= **期末股数**。
* 东财 `bps` 与新浪「每股净资产_调整前/后」的股数基准亦不一致。

实测同一公司-年两边比值可差 1.7~3.4 倍，**该差异多数不是重述**。故本脚本
**只落盘、不覆盖**东财文件，产出独立目录，由消费端按 `docs/archive/Ashare_pit_judgment_protocol.md`
§7.5 显式选择口径。

另：两边的 `加权净资产收益率` 字段都有坏值（东财 600217·2013 给出「亏 1.17 亿却 ROE +35.49」；
新浪 600448·2009 给出 −0.27 而其自身净资产收益率为 −31.97）。**优先用新浪的
`净资产收益率(%)`**，它在判例上与 `EPS/BPS` 推算值精确吻合。

用法::

    python3 scripts/fetch_sina_original_financials.py --pairs-file <每行 代码,年份>
    python3 scripts/fetch_sina_original_financials.py --codes 002450 --years 2015-2018
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/archive/financials_original"
URL = ("https://money.finance.sina.com.cn/corp/go.php/vFD_FinancialGuideLine"
       "/stockid/{code}/ctrl/{year}/displaytype/4.phtml")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
SOURCE = "sina vFD_FinancialGuideLine"

CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TABLE = re.compile(r'id="BalanceSheetNewTable0".*?</table>', re.S)

# 新浪行名 → 目标列。**行名含单位，必须逐字匹配**。
WANTED = {
    "摊薄每股收益(元)": "eps_diluted",
    "加权每股收益(元)": "eps_weighted",
    "扣除非经常性损益后的每股收益(元)": "eps_deducted",
    "每股净资产_调整前(元)": "bps_before_adj",
    "每股净资产_调整后(元)": "bps_after_adj",
    "净资产收益率(%)": "roe",                      # 首选 ROE：判例上与 EPS/BPS 推算吻合
    "加权净资产收益率(%)": "roe_weighted",          # 已知有坏值，仅留档
    "销售毛利率(%)": "gross_margin",
    "总资产(元)": "total_assets",
    "每股经营性现金流(元)": "op_cashflow_ps",
    "主营业务收入增长率(%)": "revenue_yoy",
    "净利润增长率(%)": "netprofit_yoy",
}
OUT_FIELDS = ["security_code", "report_date", *WANTED.values(), "source", "retrieved_at_utc"]


def _clean(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ").strip()


def fetch_year(code: str, year: int, timeout: float, retries: int = 3) -> list[dict]:
    """返回该年 1~4 个报告期的行。空表或取不到返回 []。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(URL.format(code=code, year=year), headers=HEADERS)
            text = urllib.request.urlopen(request, timeout=timeout).read().decode("gb18030", "ignore")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise last_exc
            time.sleep(1.5 * (attempt + 1))
    match = TABLE.search(text)
    table: dict[str, list[str]] = {}
    for row_match in ROW.finditer(match.group(0) if match else text):
        cells = [_clean(c) for c in CELL.findall(row_match.group(1))]
        if len(cells) >= 2 and cells[0]:
            table[cells[0]] = cells[1:]
    dates = table.get("报告日期") or []
    if not dates:
        return []
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    out = []
    for index, report_date in enumerate(dates):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
            continue
        row = {"security_code": code, "report_date": report_date,
               "source": SOURCE, "retrieved_at_utc": stamp}
        for sina_name, target in WANTED.items():
            values = table.get(sina_name) or []
            # **列数与报告日期不一致的行整行丢弃**——错位会把 Q1 的数当成年报的数，
            # 这类静默错位正是本轮要消灭的那类污染。
            value = values[index] if len(values) == len(dates) and index < len(values) else ""
            row[target] = "" if value in ("--", "—") else value
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="取原始披露口径财务指标（新浪）")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--pairs-file", type=Path, help="每行 `代码,年份`")
    scope.add_argument("--codes", help="逗号分隔代码，配合 --years")
    parser.add_argument("--years", help="如 2015-2018 或 2016")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--pause", type=float, default=0.4)
    args = parser.parse_args()

    pairs: list[tuple[str, int]] = []
    if args.pairs_file:
        for line in args.pairs_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            code, _, year = line.partition(",")
            pairs.append((code.strip(), int(year)))
    else:
        if not args.years:
            parser.error("--codes 需配合 --years")
        start, _, end = args.years.partition("-")
        years = range(int(start), int(end or start) + 1)
        pairs = [(c.strip(), y) for c in args.codes.split(",") if c.strip() for y in years]

    by_period: dict[str, list[dict]] = defaultdict(list)
    ok = empty = failed = 0
    for index, (code, year) in enumerate(pairs, 1):
        try:
            rows = fetch_year(code, year, args.timeout)
        except Exception as exc:                                   # noqa: BLE001
            failed += 1
            print(f"  [{index}/{len(pairs)}] {code}/{year} 失败：{type(exc).__name__}", flush=True)
            time.sleep(args.pause)
            continue
        if rows:
            ok += 1
            for row in rows:
                by_period[row["report_date"]].append(row)
        else:
            empty += 1
        if index % 50 == 0 or index == len(pairs):
            print(f"  [{index}/{len(pairs)}] 有数据 {ok}｜空 {empty}｜失败 {failed}"
                  f"｜累计 {sum(len(v) for v in by_period.values()):,} 行", flush=True)
        time.sleep(args.pause)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for period, rows in sorted(by_period.items()):
        path = args.out_dir / f"{period}.csv"
        existing: list[dict] = []
        present: set[str] = set()
        if path.exists():
            with path.open(newline="", encoding="utf-8") as handle:
                existing = list(csv.DictReader(handle))
            present = {r["security_code"] for r in existing}
        fresh = [r for r in rows if r["security_code"] not in present]
        if not fresh:
            continue
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows([*existing, *fresh])
        written += len(fresh)
    print(f"\n落盘 {written:,} 行到 {args.out_dir}／覆盖 {len(by_period)} 个报告期"
          f"｜公司-年 有数据 {ok}／空 {empty}／失败 {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

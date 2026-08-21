#!/usr/bin/env python3
"""生成**时点判定输入表**（`docs/Ashare_pit_judgment_protocol.md` 的执行工具）。

三条前视隔离全部落在本脚本里
----------------------------
1. **按公告日截断**：只输出 `notice_date <= 截断日` 的财年行。截断日取该公司
   **`--as-of-year` 当年年报的公告日**（逐公司不同，不用统一切口）。
2. **不含简称与代码**：输出块里只有序号与业务描述。代码留在索引文件里供装配回查，
   **不进入判定视野**（协议 §3.3）。
3. **不含结局字段**：不读 `full_market_screen/verdicts.csv`（含今日 `attention_class`
   与 `moat_note`）、不读 `universe_live261.csv`、不输出是否退市或末日。

重述污染的处置
--------------
凡 `restatement_contamination.csv` 标 `resolution=overridden` 的公司-年，
**改用 `data/raw/financials_original/` 的新浪原始披露值**（协议 §7.5）；
标 `unjudgeable` 的年份行输出为 `数据不可用`，**不静默丢弃**。

已知残留泄露（须记录，不假装没有）
----------------------------------
`BUSINESS_SCOPE` 与 `INDUSTRYCSRC1` 取自**今日**的 F10 公司概况。若公司在判定年之后
转型，该文本会描述转型后的业务，构成一处残留前视。财务轨迹本身不受影响。

用法::

    python3 scripts/build_judgment_input.py --as-of-year 2002 --limit 20
    python3 scripts/build_judgment_input.py --as-of-year 2010 --codes 600519,000858
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "data/raw/financials"
ORIG = ROOT / "data/raw/financials_original"
QUEUE = ROOT / "data/processed/pit_attention/judgment_queue.csv"
CONTAM = ROOT / "data/processed/pit_attention/restatement_contamination.csv"
SEC = ROOT / "data/raw/a_share_securities.csv"
PROFILE_CACHE = ROOT / "data/interim/f10_org_profile.json"
API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def _num(text):
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return None


# 可得日 = min(记录公告日, 法定截止日)——唯一实现在 `disclosure_dates.py`（OI-042，判定侧与建带侧共用）。
from disclosure_dates import available_at  # noqa: E402


def secucode(code: str) -> str:
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def load_profiles(codes: list[str]) -> dict[str, dict]:
    """F10 公司概况，带磁盘缓存。取不到的留空，**不猜**。"""
    cache = json.loads(PROFILE_CACHE.read_text()) if PROFILE_CACHE.exists() else {}
    todo = [c for c in codes if c not in cache]
    for index, code in enumerate(todo, 1):
        query = urllib.parse.urlencode({
            "reportName": "RPT_F10_BASIC_ORGINFO", "columns": "ALL", "pageSize": 1,
            "filter": f'(SECUCODE="{secucode(code)}")'})
        try:
            request = urllib.request.Request(
                f"{API}?{query}",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"})
            result = json.loads(urllib.request.urlopen(request, timeout=20).read()).get("result")
            row = (result or {}).get("data", [{}])[0] if result else {}
        except Exception:                                          # noqa: BLE001
            row = {}
        cache[code] = {k: row.get(k) for k in
                       ("INDUSTRYCSRC1", "PROVINCE", "EMP_NUM", "BUSINESS_SCOPE", "REG_CAPITAL")}
        if index % 20 == 0:
            print(f"  概况 {index}/{len(todo)}", file=sys.stderr, flush=True)
    if todo:
        PROFILE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    return cache


def load_annuals() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in sorted(FIN.glob("*-12-31.csv")):
        for row in csv.DictReader(path.open(newline="", encoding="utf-8")):
            if (row.get("notice_date") or "").strip():
                out[row["security_code"]][row["report_date"][:4]] = row
    return out


def load_originals() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    if not ORIG.exists():
        return out
    for path in sorted(ORIG.glob("*-12-31.csv")):
        for row in csv.DictReader(path.open(newline="", encoding="utf-8")):
            out[row["security_code"]][row["report_date"][:4]] = row
    return out


def describe(code: str, profile: dict, sec: dict) -> str:
    industry = (profile.get("INDUSTRYCSRC1") or sec.get("industry") or "行业不详").strip()
    province = (profile.get("PROVINCE") or sec.get("region") or "").strip()
    scope = re.sub(r"\s+", "", profile.get("BUSINESS_SCOPE") or "")[:110]
    emp = profile.get("EMP_NUM")
    bits = [industry]
    if province:
        bits.append(province)
    if emp and str(emp).isdigit() and int(emp) > 1:
        bits.append(f"员工{int(emp):,}人")
    head = "｜".join(bits)
    return f"{head}\n    经营范围：{scope}" if scope else head


def main() -> int:
    parser = argparse.ArgumentParser(description="生成时点判定输入表")
    parser.add_argument("--as-of-year", type=int, required=True)
    parser.add_argument("--codes", help="逗号分隔；缺省取该年首次签名的公司")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    queue = list(csv.DictReader(QUEUE.open(newline="", encoding="utf-8")))
    if args.codes:
        wanted = [c.strip() for c in args.codes.split(",") if c.strip()]
        rows = [r for r in queue if r["security_code"] in wanted]
    else:
        rows = [r for r in queue if int(r["first_sig_year"]) == args.as_of_year]
    rows = rows[args.offset:args.offset + args.limit]
    if not rows:
        print("该批次为空")
        return 1

    codes = [r["security_code"] for r in rows]
    annuals, originals = load_annuals(), load_originals()
    profiles = load_profiles(codes)
    sec = {}
    for row in csv.DictReader(SEC.open(newline="", encoding="utf-8")):
        key = next(k for k in row if k.endswith("security_code"))
        sec[row[key]] = row
    override: dict[str, dict[str, str]] = defaultdict(dict)
    for row in csv.DictReader(CONTAM.open(newline="", encoding="utf-8")):
        override[row["security_code"]][row["year"]] = row["resolution"]

    blocks, index = [], []
    for number, row in enumerate(rows, 1):
        code = row["security_code"]
        series = annuals.get(code, {})
        anchor = series.get(str(args.as_of_year)) or {}
        cutoff = available_at(anchor.get("report_date", ""), anchor.get("notice_date", "")) \
            if anchor.get("notice_date") else None
        if not cutoff:
            continue                          # 该年年报未披露 → 该时点无从判起
        lines = []
        for year in sorted(series):
            fin = series[year]
            if available_at(fin["report_date"], fin["notice_date"]) > cutoff:
                continue                      # **前视闸门**（用封顶后的可见日，见 available_at）
            state = override.get(code, {}).get(year)
            if state == "unjudgeable":
                lines.append(f"    {year}   —— 该年数据经检出重述污染且无原始值，不可用")
                continue
            src = originals.get(code, {}).get(year) if state == "overridden" else None
            if src:
                roe = _num(src.get("roe_weighted")) or _num(src.get("roe"))
                eps, bps = _num(src.get("eps_weighted")), _num(src.get("bps_after_adj"))
                gross = _num(src.get("gross_margin"))
                rev = pro = None
                tag = "原值"
            else:
                roe = _num(fin.get("weightavg_roe"))
                eps, bps = _num(fin.get("basic_eps")), _num(fin.get("bps"))
                gross = _num(fin.get("gross_margin"))
                rev = _num(fin.get("total_operate_income"))
                pro = _num(fin.get("parent_netprofit"))
                tag = ""
            fmt = (f"    {year}   营收 {rev/1e8:>8.1f}亿" if rev is not None else f"    {year}   营收      ——")
            fmt += (f"  归母净利 {pro/1e8:>7.2f}亿" if pro is not None else "  归母净利     ——")
            fmt += f"  ROE {roe:>6.1f}%" if roe is not None else "  ROE     ——"
            fmt += f"  毛利率 {gross:>5.1f}%" if gross is not None else "  毛利率    ——"
            fmt += f"  BPS {bps:>6.2f}" if bps is not None else ""
            fmt += f"  EPS {eps:>6.3f}" if eps is not None else ""
            if tag:
                fmt += f"   [{tag}]"
            lines.append(fmt)
        listing = (sec.get(code, {}) or {}).get("listing_date") or row["first_traded"]
        years_listed = args.as_of_year - int(listing[:4]) if listing else None
        blocks.append(
            f"### 待判 {number}\n"
            f"  {describe(code, profiles.get(code, {}), sec.get(code, {}))}\n"
            f"  上市：{listing}（截至 {args.as_of_year} 年末满 {years_listed} 年）\n"
            f"  截断日（{args.as_of_year} 年报可见日，已按法定截止日封顶）：{cutoff}\n"
            f"  逐年轨迹（**只含公告日 ≤ 截断日的财年**）：\n" + "\n".join(lines))
        index.append({"number": number, "security_code": code, "as_of_year": args.as_of_year,
                      "cutoff_notice": cutoff})

    text = (f"# 时点判定输入 · as-of {args.as_of_year} · {len(blocks)} 家\n"
            f"# 判定只许引用上表内的信息，禁止使用任何公告日晚于各自截断日的事实\n\n"
            + "\n\n".join(blocks))
    out = args.out or (ROOT / f"data/interim/judgment_input_{args.as_of_year}"
                              f"_{args.offset}_{args.offset + len(blocks)}.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    (out.with_suffix(".index.csv")).write_text(
        "number,security_code,as_of_year,cutoff_notice\n"
        + "".join(f"{r['number']},{r['security_code']},{r['as_of_year']},{r['cutoff_notice']}\n"
                 for r in index), encoding="utf-8")
    print(f"输入表 {len(blocks)} 家 → {out}")
    print(f"索引 → {out.with_suffix('.index.csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

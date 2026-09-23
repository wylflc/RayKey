#!/usr/bin/env python3
"""年报附注中的现金类项目抽取（§6.5.1 超额现金口径，OI-201）。

三大报表把定期存款、大额存单、银行理财等放在哪一行取决于公司口径：货币资金、交易性金融资产之外，
常见于其他流动资产、一年内到期的非流动资产、其他非流动资产（2019 年新金融工具准则前，银行理财多在
其他流动资产）。报表只给行合计，构成只在附注。本脚本对「三行合计 ≥ 归母权益 × 下限」的一般企业年报
逐份下载巨潮原文、抽取三行附注表中的现金类明细，按原年报公告日生效（原版，不用更正后版本）。

    python3 scripts/fetch_cash_note_items.py --plan                 # 只列待抽取的 (代码, 财年)
    python3 scripts/fetch_cash_note_items.py --workers 16           # 下载并缓存原文文本（已缓存跳过），再解析写表
    python3 scripts/fetch_cash_note_items.py --parse-only           # 只用缓存文本重解析（改解析规则后）
    python3 scripts/fetch_cash_note_items.py --codes 000333 --years 2025 --refresh

产物：
  data/reference/cash_note_items.csv   逐 (代码, 财年, 行) 一行：报表行值、附注合计、现金类合计、明细、状态
  data/raw/annual_reports/             原文 PDF 与文本缓存（不入库，按本脚本重建）

判定：附注合计与报表行值相差 ≤ 5%（或 100 万元，只用来确认表与单位）且明细之和与合计相符才算核定（`status = ok`）；其余状态该行按经营资产处理，
与改前口径相同。现金类 = 标签含存款、存单、理财、结构性、逆回购、收益凭证、信托、资管计划、货币基金、
国债、债券、债权投资之一，且不含贷款、保理、融资租赁、税费、预付、合同成本等经营或信贷项。
"""
from __future__ import annotations

import argparse
from itertools import combinations
import csv
import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STMT = ROOT / "data/raw/financials_statements/balance.csv"
OUT = ROOT / "data/reference/cash_note_items.csv"
CACHE = ROOT / "data/raw/annual_reports"
LINES = {"OTHER_CURRENT_ASSET": "其他流动资产", "NONCURRENT_ASSET_1YEAR": "一年内到期的非流动资产",
         "OTHER_NONCURRENT_ASSET": "其他非流动资产"}
MATERIALITY = 0.02            # 三行合计 ≥ 归母权益 × 2% 才抽取
FIRST_YEAR = 2007
CASH_KEYS = ("存款", "存单", "理财", "结构性", "逆回购", "收益凭证", "信托", "资产管理计划", "资管计划",
             "货币基金", "货币市场基金", "国债", "债券", "债权投资", "货币性投资", "现金管理", "固定收益", "持有至到期")
NON_CASH_KEYS = ("贷款", "保理", "融资租赁", "进项税", "税额", "税金", "税款", "预缴", "预付", "待抵扣", "待认证",
                 "退货", "合同取得", "合同履约", "碳排放", "抵债", "保证金", "押金", "应收账款", "应收票据", "应收款项",
                 "应收退", "应收代位", "长期应收", "备付金")
FIELDS = ["security_code", "security_name", "fiscal_year", "report_date", "line", "line_label", "statement_amount",
          "notes_total", "cash_like_amount", "items", "unit", "status", "announcement_date", "title", "url",
          "extracted_at_utc"]
AMOUNT = re.compile(r"-?\d{1,3}(?:,\d{3})+\.\d{2}|-?\d+\.\d{2}")          # 带两位小数（元）
INTEGER = re.compile(r"-?\d{1,3}(?:,\d{3})+(?![\d.])|(?<![\d,.])-?\d{1,3}(?![\d,.])")   # 千元／万元表常见的整数
TOTAL_TOLERANCE = 0.05     # 附注合计与报表行值的容差：只用来确认表与单位，行值被次年重述时常差几个百分点
UA = {"User-Agent": "Mozilla/5.0"}


def _num(text) -> float:
    try:
        return float(text) if text not in (None, "") else 0.0
    except ValueError:
        return 0.0


def plan(codes: set[str] | None, years: set[int] | None) -> list[dict]:
    """(代码, 财年) 待抽取清单：一般企业模板年报、三行合计 ≥ 归母权益 × MATERIALITY。"""
    out = []
    with STMT.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("org_table") != "RPT_F10_FINANCE_GBALANCE" or not row["REPORT_DATE"][:10].endswith("12-31"):
                continue
            code, year = row["security_code"].zfill(6), int(row["REPORT_DATE"][:4])
            if year < FIRST_YEAR or (codes and code not in codes) or (years and year not in years):
                continue
            eq = _num(row.get("TOTAL_PARENT_EQUITY"))
            lines = {k: _num(row.get(k)) for k in LINES}
            if eq > 0 and sum(lines.values()) >= MATERIALITY * eq:
                out.append(dict(code=code, name=row.get("SECURITY_NAME_ABBR", ""), year=year,
                                report_date=row["REPORT_DATE"][:10], lines=lines))
    return sorted(out, key=lambda r: (r["code"], r["year"]))


def http(url: str, data: bytes | None = None, tries: int = 4, timeout: int = 60) -> bytes:
    for attempt in range(tries):
        try:
            headers = dict(UA)
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout).read()
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(url)


def org_id(code: str, cache: dict) -> tuple[str, str]:
    if code not in cache:
        data = urllib.parse.urlencode(dict(keyWord=code, maxNum=5)).encode()
        hits = json.loads(http("http://www.cninfo.com.cn/new/information/topSearch/query", data))
        hit = next((h for h in hits if h.get("code") == code), None)
        if hit is None:
            raise LookupError(f"巨潮无 {code}")
        column = "sse" if code.startswith(("6", "9")) else "bj" if code.startswith(("4", "8")) else "szse"
        cache[code] = [hit["orgId"], column]
    return tuple(cache[code])


def find_report(code: str, year: int, orgs: dict) -> dict | None:
    """该财年年报原版（最早公告、非摘要／英文）的公告日、标题与链接。"""
    org, column = org_id(code, orgs)
    data = urllib.parse.urlencode(dict(pageNum=1, pageSize=50, column=column, tabName="fulltext", plate="",
                                       stock=f"{code},{org}", searchkey="", secid="", category="category_ndbg_szsh",
                                       trade="", seDate=f"{year + 1}-01-01~{year + 2}-06-30", sortName="",
                                       sortType="", isHLtitle="true")).encode()
    rows = json.loads(http("http://www.cninfo.com.cn/new/hisAnnouncement/query", data)).get("announcements") or []
    cands = []
    for a in rows:
        title = re.sub(r"</?em>", "", a.get("announcementTitle") or "")
        if str(year) not in title or not re.search(r"年度报告|年报", title) or re.search(r"摘要|英文|English|提示", title):
            continue
        cands.append(dict(date=beijing_day(a), title=title, url="http://static.cninfo.com.cn/" + a["adjunctUrl"]))
    if not cands:
        return None
    return min(cands, key=lambda c: (c["date"], "更新" in c["title"] or "修订" in c["title"] or "更正" in c["title"]))


def beijing_day(announcement: dict) -> str:
    """公告日（北京时间）：优先取链接路径 `finalpage/YYYY-MM-DD/`，缺失时按 Asia/Shanghai 换算时间戳。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", announcement.get("adjunctUrl") or "")
    if m:
        return m.group(1)
    return datetime.fromtimestamp(announcement["announcementTime"] / 1000, tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def report_text(code: str, year: int, url: str, refresh: bool) -> str:
    from pypdf import PdfReader
    folder = CACHE / code
    folder.mkdir(parents=True, exist_ok=True)
    txt = folder / f"{year}.txt.gz"
    if txt.exists() and not refresh:
        return gzip.decompress(txt.read_bytes()).decode("utf-8")
    pdf = folder / f"{year}.pdf"
    if refresh or not pdf.exists():
        pdf.write_bytes(http(url, timeout=120))
    text = "\n".join((page.extract_text() or "") for page in PdfReader(str(pdf)).pages)
    txt.write_bytes(gzip.compress(text.encode("utf-8")))
    return text


def _unit(window: str) -> float | None:
    m = re.search(r"单位\s*[:：]\s*(百万元|万元|千元|元)", window)
    return {"元": 1.0, "千元": 1e3, "万元": 1e4, "百万元": 1e6}[m.group(1)] if m else None


def _pattern(text: str) -> tuple[re.Pattern, str]:
    """金额格式：出现两位小数即按小数切分，否则按千分位整数（千元／万元表）。"""
    return (AMOUNT, r"(?<=[\d,.])[ \t]*\n[ \t]*(?=[\d,.])") if AMOUNT.search(text) else (INTEGER, r"(?<=,)[ \t]*\n[ \t]*(?=\d)")


def _amounts(text: str, mode: tuple[re.Pattern, str] | None = None) -> list[float]:
    """把 PDF 断行的长数字拼回后切分金额（小数格式按「两位小数」切分；整数格式只拼逗号处断开的数）。"""
    pattern, join = mode or _pattern(text)
    joined = re.sub(join, "", text)
    return [float(x.replace(",", "")) for x in pattern.findall(joined)]


def notes_start(text: str) -> int:
    """合并报表项目注释的正文起点：标题后 300 字内出现「1、货币资金」的那一次（目录与正文引用不算）。"""
    best = 0
    for key in ("合并财务报表项目注释", "合并财务报表主要项目注释", "合并会计报表项目注释", "合并会计报表主要项目注释",
                "财务报表主要项目注释", "财务报表项目注释", "会计报表主要项目注释", "会计报表项目注释",
                "合并财务报表项目附注", "合并财务报表主要项目附注"):
        for m in re.finditer(key, text):
            if re.search(r"(?:\d{1,2}\s*[、．.]|[（(](?:一|1)[)）])\s*货币资金", text[m.end():m.end() + 300]):
                return m.start()
            best = best or m.start()
    return best


def section(text: str, label: str, start: int) -> str | None:
    """附注中以「序号 + 行名」开头、其后 300 字内出现表头的那一段（至多 4000 字，由调用方截到合计行）。"""
    # 标题在行首、其后不跟引号：正文里「详见附注“五、28、其他非流动资产”」一类交叉引用不算
    pattern = re.compile(r"(?:^|\n)[ \t]*(?:\d{1,3}\s*[、．.]|[（(](?:[一二三四五六七八九十百]+|\d{1,3})[)）])\s*"
                         + re.escape(label) + r"(?![\u4e00-\u9fa5”\"])")
    for m in pattern.finditer(text, start):
        head = text[m.end():m.end() + 300]
        if re.search(r"项\s*目|单位|适用|期末|年末|\d{4}\s*年\s*\d{1,2}\s*月", head):
            return text[m.end():m.end() + 4000]
    return None


def _classify(label: str) -> bool:
    """现金类判定：末行有关键词按末行，否则按整段标签；非现金词优先。"""
    lines = [x for x in re.split(r"[\n|]", label) if x.strip()]
    for text in ([lines[-1]] if lines else []) + [re.sub(r"\s+", "", label)]:     # 整段去空白：断行拆开的「理\n财产品」
        if any(bad in text for bad in NON_CASH_KEYS):
            return False
        if any(key in text for key in CASH_KEYS):
            return True
    return False


def table_rows(table: str, mode: tuple[re.Pattern, str]) -> list[tuple[str, list[float]]]:
    """表体 → [(标签, 金额列)]：长数字断行先拼回，相邻金额归同一行，两组金额之间的文字是下一行的标签。"""
    pattern, join = mode
    joined = re.sub(join, "", table)
    rows, last, current, label = [], 0, [], ""
    for m in pattern.finditer(joined):
        gap = joined[last:m.start()]
        if current and re.fullmatch(r"[\s|/—\-]*", gap):
            current.append(float(m.group().replace(",", "")))
        else:
            if current:
                rows.append((label, current))
            label, current = gap, [float(m.group().replace(",", ""))]
        last = m.end()
    if current:
        rows.append((label, current))
    return rows


def parse_section(body: str, statement_amount: float) -> dict:
    """附注表 → 合计、现金类明细与单位；合计须与报表行值相符（≤ TOTAL_TOLERANCE 或 100 万元），明细之和须与合计相符。"""
    unit = _unit(body)
    units = [unit] if unit else [1.0, 1e4, 1e3, 1e6]
    # 附注引用与脚注标记（「(附注四(12))」「(a)」「【注】」）里的数字不是金额
    body = re.sub(r"[（(]\s*(?:附注|注)[^（()）\n]*(?:[（(][^（()）\n]*[)）][^（()）\n]*)?[)）]", "", body)
    body = re.sub(r"[（(][a-zA-Z]{1,2}[)）]|【注\d*】|\[注\d*\]", "", body)

    def matches(vals):
        return next((u for u in units for t in vals
                     if abs(t * u - statement_amount) <= max(TOTAL_TOLERANCE * abs(statement_amount), 1e6)), None)

    candidates = []
    m = re.search(r"合\s*计", body)
    if m:
        tail = body[m.end():m.end() + 300]
        stop = re.search(r"\d[^\n]*\n\s*[\u4e00-\u9fa5（(]", tail)      # 合计行到下一行中文起始为止（表后说明常含利率等小数）
        candidates.append(((tail[:stop.end() - 1] if stop else tail), body[:m.start()]))
    # 无「合计」字样的版式（合计行只有数字）：首个数与报表行值最接近的纯数字行（行值折行后也是纯数字行，取最接近者）
    best = None
    for line in re.finditer(r"(?m)^[ \t]*((?:-?[\d,]+(?:\.\d+)?[ \t]*){1,6})$", body[:2500]):
        first = _amounts(line.group(1))[:1]
        if not first or not matches(first):
            continue
        err = min(abs(first[0] * u - statement_amount) for u in units)
        if best is None or err < best[0]:
            best = (err, line)
    if best is not None:
        candidates.append((best[1].group(1), body[:best[1].start()]))
    if not candidates:
        return dict(notes_total=None, unit=unit or "", cash=0.0, items="", status="no_total")
    chosen = total_vals = table = mode = None
    for total_row, table_text in candidates:
        mode_try = _pattern(table_text + total_row)
        vals = _amounts(total_row, mode_try)[:3]
        unit_try = matches(vals)
        if unit_try is not None:
            chosen, total_vals, table, mode = unit_try, vals, table_text, mode_try
            break
    if chosen is None:
        first = _amounts(candidates[0][0])[:1]
        return dict(notes_total=first[0] if first else None, unit=unit or "", cash=0.0,
                    items="", status="total_mismatch" if first else "no_total")
    rows = table_rows(table, mode)
    gross = total_vals[0]
    # 「其中：」子行与「小计」行是其他行的拆分或加总，不进合计核对也不作明细（否则母项会被当成空白行剔除）
    rows = [(lab, vals) for lab, vals in rows
            if not re.match(r"\s*(?:其\s*中\s*[:：]|小\s*计)", ([x for x in re.split(r"[\n|]", lab) if x.strip()] or [""])[-1])]
    signed = [(-1.0 if re.search(r"减\s*[:：]", lab) else 1.0) * vals[0] for lab, vals in rows]
    # 本期单元格空白的行只剩上期数，首列即上期：找首列之和恰等于超出合计部分的 1～3 行，本期记 0
    blank: set[int] = set()
    excess = sum(signed) - gross
    tol = max(0.002 * abs(gross), 1.0)
    if rows and abs(excess) > tol:
        for size in (1, 2, 3):
            hit = next((c for c in combinations(range(len(rows)), size) if abs(sum(signed[i] for i in c) - excess) <= tol), None)
            if hit:
                blank = set(hit)
                break
    items = [(re.sub(r"\s+", "", lab)[-40:], v) for i, ((lab, _), v) in enumerate(zip(rows, signed))
             if _classify(lab) and i not in blank]
    cash = sum(v for _, v in items) * chosen
    status = "ok"
    if rows and abs(excess) > tol and not blank:
        status = "rows_mismatch"
    elif not (-0.01 * abs(statement_amount) <= cash <= 1.01 * abs(statement_amount)):
        status = "cash_exceeds_total"
    detail = [(re.sub(r"\s+", "", lab)[-40:], v * chosen, _classify(lab)) for i, ((lab, _), v) in enumerate(zip(rows, signed))
              if i not in blank]
    return dict(notes_total=gross * chosen, unit=chosen, cash=cash if status == "ok" else 0.0,
                items=";".join(f"{lab}:{v * chosen:.2f}" for lab, v in items), status=status, rows=detail)


def locate(task: dict, orgs: dict, refresh: bool) -> dict:
    """串行定位年报原文（检索接口限流，不并发）；元数据写 `<代码>/<财年>.json`，状态 located／report_not_found。"""
    folder = CACHE / task["code"]
    meta_path = folder / f"{task['year']}.json"
    if meta_path.exists() and not refresh:
        meta = json.loads(meta_path.read_text())
        if meta.get("status") in ("ok", "located", "report_not_found"):
            return meta
    folder.mkdir(parents=True, exist_ok=True)
    try:
        rep = find_report(task["code"], task["year"], orgs)
    except Exception as exc:                                     # noqa: BLE001 - recorded as status
        return dict(status=f"query_error:{type(exc).__name__}")
    meta = dict(status="located", **rep) if rep else dict(status="report_not_found")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False))
    return meta


def fetch_report(task: dict, meta: dict, refresh: bool) -> dict:
    """下载已定位的原文并缓存文本（进程池调用，不访问检索接口）。"""
    folder = CACHE / task["code"]
    if meta.get("status") != "located" and not (refresh and meta.get("status") == "ok"):
        return meta
    try:
        report_text(task["code"], task["year"], meta["url"], refresh)
    except Exception as exc:                                     # noqa: BLE001
        return dict(meta, status=f"download_error:{type(exc).__name__}")
    meta = dict(meta, status="ok")
    (folder / f"{task['year']}.json").write_text(json.dumps(meta, ensure_ascii=False))
    return meta


def parse_task(task: dict, meta: dict) -> list[dict]:
    """缓存文本 → 三行附注逐行结果（无网络）。"""
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    day = re.search(r"finalpage/(\d{4}-\d{2}-\d{2})/", meta.get("url", ""))
    base = dict(security_code=task["code"], security_name=task["name"], fiscal_year=task["year"],
                report_date=task["report_date"], extracted_at_utc=stamp,
                announcement_date=day.group(1) if day else meta.get("date", ""),
                title=meta.get("title", ""), url=meta.get("url", ""))
    rows = []
    if meta.get("status") != "ok":
        for key, label in LINES.items():
            if task["lines"][key]:
                rows.append(dict(base, line=key, line_label=label, statement_amount=f"{task['lines'][key]:.2f}",
                                 cash_like_amount="0.00", status=meta.get("status", "missing")))
        return rows
    text = gzip.decompress((CACHE / task["code"] / f"{task['year']}.txt.gz").read_bytes()).decode("utf-8")
    start = notes_start(text)
    parsed_by_line = {}
    for key, label in LINES.items():
        amount = task["lines"][key]
        if not amount:
            continue
        body = section(text, label, start) or section(text, label, 0)
        parsed_by_line[key] = (parse_section(body, amount) if body is not None
                               else dict(notes_total=None, unit="", cash=0.0, items="", status="section_not_found"))
    # 一年内到期行里的泛称条目（「一年内到期的其他非流动资产」）若与其他非流动资产附注中现金类的
    # 「减：一年内到期…」行等额，即为同一批存款的重分类，按现金计
    one_year, onca = parsed_by_line.get("NONCURRENT_ASSET_1YEAR"), parsed_by_line.get("OTHER_NONCURRENT_ASSET")
    if one_year and onca and one_year["status"] == "ok" and onca.get("rows"):
        moved = [-v for lab, v, is_cash in onca["rows"] if is_cash and v < 0]
        for lab, v, is_cash in one_year.get("rows", []):
            if not is_cash and "其他非流动资产" in lab and any(abs(v - m) <= max(0.01 * abs(m), 1.0) for m in moved):
                one_year["cash"] += v
                one_year["items"] = ";".join(filter(None, [one_year["items"], f"{lab}（对应其他非流动资产附注的现金类重分类）:{v:.2f}"]))
    for key, label in LINES.items():
        amount = task["lines"][key]
        if not amount:
            continue
        parsed = parsed_by_line[key]
        rows.append(dict(base, line=key, line_label=label, statement_amount=f"{amount:.2f}",
                         notes_total=("" if parsed["notes_total"] in (None, "") else f"{parsed['notes_total']:.2f}"),
                         cash_like_amount=f"{parsed['cash']:.2f}", items=parsed["items"], unit=parsed["unit"],
                         status=parsed["status"]))
    return rows


def load_existing() -> dict[tuple[str, int], list[dict]]:
    out: dict[tuple[str, int], list[dict]] = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                out.setdefault((row["security_code"], int(row["fiscal_year"])), []).append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--codes", help="逗号分隔")
    parser.add_argument("--years", help="逗号分隔财年")
    parser.add_argument("--plan", action="store_true", help="只打印清单规模")
    parser.add_argument("--refresh", action="store_true", help="重下原文")
    parser.add_argument("--parse-only", action="store_true", help="只用已缓存文本解析，不联网")
    parser.add_argument("--workers", type=int, default=8, help="下载与文本提取的进程数")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    codes = {c.strip().zfill(6) for c in args.codes.split(",")} if args.codes else None
    years = {int(y) for y in args.years.split(",")} if args.years else None
    tasks = plan(codes, years)
    if args.limit:
        tasks = tasks[:args.limit]
    print(f"清单 {len(tasks)} 份年报（{len({t['code'] for t in tasks})} 家）", flush=True)
    if args.plan:
        return 0
    CACHE.mkdir(parents=True, exist_ok=True)
    metas: dict[tuple[str, int], dict] = {}
    if not args.parse_only:
        orgs_path = CACHE / "orgid.json"
        orgs = json.loads(orgs_path.read_text()) if orgs_path.exists() else {}
        for code in sorted({t["code"] for t in tasks}):      # 先串行解析 orgId
            try:
                org_id(code, orgs)
            except Exception as exc:                          # noqa: BLE001
                print(f"  ⚠ {code} orgId 失败：{exc}", flush=True)
        orgs_path.write_text(json.dumps(orgs, ensure_ascii=False, indent=0))
        todo = [t for t in tasks if t["code"] in orgs]
        for i, t in enumerate(todo, 1):                      # 第一段：串行定位（检索接口限流）
            before = (CACHE / t["code"] / f"{t['year']}.json").exists()
            metas[(t["code"], t["year"])] = locate(t, orgs, args.refresh)
            if not before:
                time.sleep(0.3)
            if i % 200 == 0 or i == len(todo):
                print(f"  定位 {i}/{len(todo)}", flush=True)
        pending = [t for t in todo if metas[(t["code"], t["year"])].get("status") == "located"
                   or (args.refresh and metas[(t["code"], t["year"])].get("status") == "ok")]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:   # 第二段：并行下载与文本提取
            futures = {pool.submit(fetch_report, t, metas[(t["code"], t["year"])], args.refresh): t for t in pending}
            for i, fut in enumerate(as_completed(futures), 1):
                t = futures[fut]
                metas[(t["code"], t["year"])] = fut.result()
                if i % 100 == 0 or i == len(pending):
                    print(f"  下载 {i}/{len(pending)}", flush=True)
    for t in tasks:
        path = CACHE / t["code"] / f"{t['year']}.json"
        if (t["code"], t["year"]) not in metas:
            metas[(t["code"], t["year"])] = json.loads(path.read_text()) if path.exists() else dict(status="not_fetched")
    existing = load_existing()
    results = {(t["code"], t["year"]): parse_task(t, metas[(t["code"], t["year"])]) for t in tasks}
    merged = {**existing, **results}
    write(merged)
    rows = [r for rs in merged.values() for r in rs]
    stats: dict[str, int] = {}
    for r in rows:
        key = (r.get("status") or "").split(":")[0]
        stats[key] = stats.get(key, 0) + 1
    ok_value = sum(_num(r.get("statement_amount")) for r in rows if r.get("status") == "ok")
    all_value = sum(_num(r.get("statement_amount")) for r in rows) or 1.0
    cash_value = sum(_num(r.get("cash_like_amount")) for r in rows)
    print(f"行状态：{stats}；核定覆盖报表金额 {ok_value / all_value:.1%}；现金类占核定金额 {cash_value / max(ok_value, 1):.1%}")
    return 0


def write(merged: dict) -> None:
    rows = sorted((r for rs in merged.values() for r in rs), key=lambda r: (r["security_code"], int(r["fiscal_year"]), r["line"]))
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(OUT)


if __name__ == "__main__":
    sys.exit(main())

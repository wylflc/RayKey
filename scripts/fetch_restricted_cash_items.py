#!/usr/bin/env python3
"""年报受限资产附注中为应付票据质押的现金类抽取（§6.5.1 超额现金口径，OI-219）。

爱玛、格力等靠银行承兑汇票付款的公司把定期存单、票据保证金质押给银行开票：存单计入了超额现金，
其担保的应付票据又按经营负债（垫款）处理，同一笔资金计了两次。本脚本对「应付票据 ≥ 归母权益 × 下限」
的一般企业年报读「所有权或使用权受限资产」附注（缺失时读管理层讨论的「主要资产受限情况」表），
逐行取期末账面价值、受限原因（含「注 N」脚注原文），按用户 2026-09-25 裁定的口径计数：

* 现金类行（货币资金、存单、定期存款、交易性金融资产、债权投资、一年内到期的非流动资产、其他流动资产、
  其他非流动资产等）且原因含票据、承兑、汇票、信用证或保函之一的整行计入（同一行混写借款的也计入）；
  只写借款的不计；其余原因（笼统的「质押」「保证金」、冻结、存款准备金等）另列 `generic_yuan`，不计入。
* 附注三行（其他流动资产、一年内到期的非流动资产、其他非流动资产）只有 `cash_note_items.csv` 核定为现金的部分
  进了超额现金，计入额以该行核定现金为限；其余现金类行以报表行值为限。
* 以当期应付票据封顶在 `roic_inputs` 里做（同一份报表），本表只给 `counted_yuan`。

    python3 scripts/fetch_restricted_cash_items.py --plan
    python3 scripts/fetch_restricted_cash_items.py --workers 24        # 定位、下载（与现金附注共用缓存）、解析写表
    python3 scripts/fetch_restricted_cash_items.py --parse-only        # 只用缓存文本重解析
    python3 scripts/fetch_restricted_cash_items.py --codes 603529 --years 2025 --parse-only --show

产物 `data/reference/restricted_cash_items.csv`：逐 (代码, 财年) 一行；`status = ok` 表示逐行期末值之和与附注合计相符，
其余状态不扣（与改前口径相同）。原文按年报原版公告日生效，缓存 `data/raw/annual_reports/` 与 `fetch_cash_note_items.py` 共用。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_cash_note_items as cn  # noqa: E402

ROOT = cn.ROOT
OUT = ROOT / "data/reference/restricted_cash_items.csv"
CASH_NOTES = cn.OUT
MATERIALITY = 0.02            # 应付票据 ≥ 归母权益 × 2% 才抽取（与现金附注同一门槛）
FIELDS = ["security_code", "security_name", "fiscal_year", "report_date", "notes_payable", "restricted_total",
          "cash_like_yuan", "counted_yuan", "generic_yuan", "loan_only_yuan", "items", "source", "status",
          "announcement_date", "title", "url", "extracted_at_utc"]
HEADING = re.compile(r"(?:^|\n)[ \t]*(?:(\d{1,3})\s*[、．.]\s*|[（(](?:[一二三四五六七八九十百]+|\d{1,3})[)）]\s*)"
                     r"所\s*有\s*权\s*(?:或\s*使\s*用\s*权\s*)?受\s*(?:到\s*)?限\s*(?:制\s*)?(?:的\s*)?资\s*产")
NONE_STATED = re.compile(r"不存在(?:主要)?资产(?:被查封、扣押、冻结或者?被抵押、质押等)?(?:权利)?受限|无(?:所有权或使用权)?受限(?:制)?(?:的)?资产|不存在所有权或使用权受(?:到)?限(?:制)?")
MDA = re.compile(r"(?:主要资产受限情况|资产权利受限情况|主要资产被查封、扣押、冻结或者被抵押、质押情况)")
# 资产负债表行名与附注常见子项；按长度降序匹配（「其他非流动资产」先于「非流动资产」）
ITEMS = sorted({
    "货币资金", "其他货币资金", "银行存款", "定期存款", "大额存单", "定期存单", "存单", "保证金存款", "银行承兑汇票保证金",
    "交易性金融资产", "以公允价值计量且其变动计入当期损益的金融资产", "债权投资", "其他债权投资", "持有至到期投资",
    "一年内到期的非流动资产", "其他流动资产", "其他非流动资产", "理财产品", "结构性存款", "应收票据", "应收账款",
    "应收款项融资", "预付款项", "其他应收款", "存货", "合同资产", "长期应收款", "长期股权投资", "其他权益工具投资",
    "其他非流动金融资产", "可供出售金融资产", "投资性房地产", "固定资产", "在建工程", "生产性生物资产", "使用权资产",
    "无形资产", "开发支出", "长期待摊费用", "应收利息", "土地使用权", "房屋建筑物", "房屋及建筑物", "机器设备",
    "子公司股权", "股权", "持有待售资产", "发放贷款和垫款", "发放贷款及垫款", "买入返售金融资产", "应收保理款",
    "应收融资租赁款", "一年内到期的长期应收款", "股权投资", "应收票据及应收账款", "应收账款及应收票据", "其他资产",
}, key=len, reverse=True)
CASH_ITEMS = {"货币资金", "其他货币资金", "银行存款", "定期存款", "大额存单", "定期存单", "存单", "保证金存款",
              "银行承兑汇票保证金", "交易性金融资产", "以公允价值计量且其变动计入当期损益的金融资产", "债权投资",
              "其他债权投资", "持有至到期投资", "一年内到期的非流动资产", "其他流动资产", "其他非流动资产",
              "理财产品", "结构性存款"}
NOTE_LINES = {"其他流动资产": "OTHER_CURRENT_ASSET", "一年内到期的非流动资产": "NONCURRENT_ASSET_1YEAR",
              "其他非流动资产": "OTHER_NONCURRENT_ASSET"}
BALANCE_FIELD = {"货币资金": "MONETARYFUNDS", "交易性金融资产": "TRADE_FINASSET",
                 "以公允价值计量且其变动计入当期损益的金融资产": "TRADE_FINASSET",
                 "债权投资": "CREDITOR_INVEST", "其他债权投资": "OTHER_CREDITOR_INVEST", "持有至到期投资": "HOLD_MATURITY_INVEST"}
NOTES_REASON = re.compile(r"票据|承兑|汇票|信用证|保函")
LOAN_REASON = re.compile(r"借款|贷款|授信|融资")
TOLERANCE = 0.005


def plan(codes: set[str] | None, years: set[int] | None) -> list[dict]:
    """(代码, 财年) 清单：一般企业模板年报、应付票据 ≥ 归母权益 × MATERIALITY（应付票据空白即 0）。"""
    out = []
    with cn.STMT.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("org_table") != "RPT_F10_FINANCE_GBALANCE" or not row["REPORT_DATE"][:10].endswith("12-31"):
                continue
            code, year = row["security_code"].zfill(6), int(row["REPORT_DATE"][:4])
            if year < cn.FIRST_YEAR or (codes and code not in codes) or (years and year not in years):
                continue
            eq, notes = cn._num(row.get("TOTAL_PARENT_EQUITY")), cn._num(row.get("NOTE_PAYABLE"))
            if eq > 0 and notes >= MATERIALITY * eq:
                balance = {f: cn._num(row.get(f)) for f in set(BALANCE_FIELD.values())}
                out.append(dict(code=code, name=row.get("SECURITY_NAME_ABBR", ""), year=year,
                                report_date=row["REPORT_DATE"][:10], notes_payable=notes, balance=balance))
    return sorted(out, key=lambda r: (r["code"], r["year"]))


def load_note_cash() -> dict[tuple[str, int, str], float]:
    """附注三行中核定为现金类的金额（`status = ok`），受限额以此为限。"""
    out: dict[tuple[str, int, str], float] = {}
    if CASH_NOTES.exists():
        with CASH_NOTES.open(encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                if r.get("status") == "ok":
                    out[(r["security_code"], int(r["fiscal_year"]), r["line"])] = cn._num(r.get("cash_like_amount"))
    return out


CASH_TABLE = re.compile(r"受\s*限\s*制\s*的\s*货\s*币\s*资\s*金\s*(?:的)?\s*(?:明\s*细|情\s*况|列\s*示)?\s*(?:如\s*下)?\s*[:：]?")


def find_section(text: str) -> tuple[str, str] | None:
    """附注「所有权或使用权受限资产」段（至下一序号标题或 6000 字）；无则管理层讨论的受限情况表；
    再无则货币资金附注里「受限制的货币资金明细」小表（2016 年前常见，行名即受限原因）。"""
    start = cn.notes_start(text)
    for m in list(HEADING.finditer(text, start)) + list(HEADING.finditer(text, 0, start)):
        head = text[m.end():m.end() + 400]
        if not re.search(r"项\s*目|单位|期末|受限|账面", head) or re.search(r"^\s*[”\"」]", head):
            continue
        body = text[m.end():m.end() + 6000]
        if m.group(1):
            nxt = re.search(r"\n[ \t]*" + str(int(m.group(1)) + 1) + r"\s*[、．.]\s*[一-龥（(]", body)
            if nxt:
                body = body[:nxt.start()]
        return body, "note"
    for m in MDA.finditer(text):
        body = text[m.end():m.end() + 3000]
        if cn.AMOUNT.search(body[:1500]) and re.search(r"受限原因|原因", body[:600]):
            stop = re.search(r"\n[ \t]*(?:\d\s*[、．.]|[（(][一二三四五六七八九十\d]+[)）])\s*[一-龥]", body[40:])
            return (body[:40 + stop.start()] if stop else body), "mda"
    for m in CASH_TABLE.finditer(text):
        body = text[m.end():m.end() + 1500]
        if re.search(r"期\s*末|年\s*末", body[:200]) and cn.AMOUNT.search(body[:600]):
            # 小表止于合计行、下一序号标题或「上述」说明，不越到下一张表
            stop = re.search(r"合\s*计[^\n]*\n|\n[ \t]*(?:[（(][一二三四五六七八九十\d]+[)）]|\d{1,2}\s*[、．.])|\n[ \t]*上述|\n[ \t]*注", body)
            return (body[:stop.end()] if stop else body[:600]), "cash_note"
    return None


def _clean(body: str) -> str:
    """去页眉页脚（「××年度报告」行、「12 / 198」页码行）与表外说明中的脚注引用标记。"""
    lines = [ln for ln in body.split("\n")
             if not re.search(r"年(?:年度|度)?报告(?:全文)?\s*$|^\s*\d{1,4}\s*/\s*\d{1,4}\s*$", ln.strip())]
    return "\n".join(lines)


def parse_section(body: str, cash_note: bool = False) -> dict:
    """附注表 → 逐行 (行名, 期末账面价值, 原因)；期末值之和须与合计相符。"""
    body = _clean(body)
    unit = cn._unit(body) or 1.0
    foot_at = re.search(r"其他说明|注\s*\d?\s*[:：]", body)
    mode = cn._pattern(body)
    pattern, join = mode
    joined = re.sub(join, "", body)
    values: list[float] = []

    def token(m: re.Match) -> str:
        values.append(float(m.group().replace(",", "")))
        return f"⟦{len(values) - 1}⟧"
    tokenized = pattern.sub(token, joined)
    synthetic = False
    flat = re.sub(r"\s+", "", tokenized)
    if "合计" not in flat and not cash_note:
        # 无「合计」字样的版式（H 股格式）：末尾连续的纯金额行里，取与各行期末值之和相符的那个数作合计（下方校验）
        lines = tokenized.split("\n")
        bare = [i for i, ln in enumerate(lines) if re.fullmatch(r"[\s\-—]*(?:⟦\d+⟧[\s\-—]*)+", ln)]
        run = []
        for i in reversed(bare):
            if run and any(re.search(r"[\u4e00-\u9fa5]", ln) for ln in lines[i + 1:run[-1]]):
                break
            run.append(i)
        if run:
            head = re.sub(r"\s+", "", "\n".join(lines[:min(run)]))
            ids = [t for i in sorted(run) for t in re.findall(r"⟦\d+⟧", lines[i])]
            flat = head + "合计" + "".join(ids)
            synthetic = True
    total_m = re.search(r"合计((?:⟦\d+⟧)+)", flat)
    if not total_m and cash_note:
        flat += "合计" + re.search(r"((?:⟦\d+⟧)+)", flat).group(1) if flat.count("⟦") and len(
            re.findall(r"[\u4e00-\u9fa5]{2,}(?:⟦\d+⟧)+", flat)) == 1 else ""      # 单行小表无合计行：该行即合计
        total_m = re.search(r"合计((?:⟦\d+⟧)+)", flat)
    if not total_m:
        return dict(status="no_total")
    table, after = flat[:total_m.start()], flat[total_m.end():]
    total_vals = [values[int(i)] for i in re.findall(r"⟦(\d+)⟧", total_m.group(1))]
    two_amounts = bool(re.search(r"账面余额.{0,12}账面价值", table[:400]))
    per = 2 if two_amounts else 1
    rows = []
    if cash_note:
        # 行 = 中文行名（即受限原因）+ 金额；首个金额为期末
        for m in re.finditer(r"([\u4e00-\u9fa5（）()、及和与/]{2,40}?)((?:⟦\d+⟧)+)", table):
            label = m.group(1)
            if re.search(r"项目|期末|年末|年初|期初|余额", label) and not re.search(r"保证金|存款|存单|冻结|质押", label):
                continue
            rows.append(dict(label="货币资金", amounts=[values[int(i)] for i in re.findall(r"⟦(\d+)⟧", m.group(2))],
                             end=m.end(), sub=label.startswith("其中"), cash_reason=label))
    item_re = "|".join(map(re.escape, ITEMS))
    # 行 = 行名紧接金额；行名前面的文字是上一行的原因
    for m in ([] if cash_note else re.finditer(r"(?:其中[:：])?(" + item_re + r")(?:[（(][^⟦）)]{0,20}[)）])?((?:⟦\d+⟧)+)", table)):
        if rows:
            rows[-1]["reason"] = table[rows[-1]["end"]:m.start()]
        rows.append(dict(label=m.group(1), amounts=[values[int(i)] for i in re.findall(r"⟦(\d+)⟧", m.group(2))],
                         end=m.end(), sub=m.group(0).startswith("其中")))
    if not rows:
        return dict(status="no_rows")
    rows[-1]["reason"] = table[rows[-1]["end"]:]
    for r in rows:                                   # 原因里夹的期初金额（新版式）不是原因
        tail = r.get("cash_reason") or r["reason"]
        extra = [values[int(i)] for i in re.findall(r"⟦(\d+)⟧", tail)]
        r["later"], r["raw"] = extra, tail
        r["reason"] = re.sub(r"⟦\d+⟧", " ", tail).strip(" /／-—")
    rows = [r for r in rows if not r["sub"]]
    target = total_vals[per - 1] if len(total_vals) >= per else total_vals[0]

    def end_value(r) -> float:
        return r["amounts"][per - 1] if len(r["amounts"]) >= per else r["amounts"][0]
    vals = [end_value(r) for r in rows]
    if synthetic:                                    # 纯金额行里与期末值之和最接近的数
        target = min(total_vals, key=lambda v: abs(v - sum(vals)))
    tol = max(TOLERANCE * abs(target), 1.0)
    excluded: set[int] = set()
    rescued = False
    if abs(sum(vals) - target) > tol:
        # 只有期初数的行（新版式期末单元格空白）：剔除 1～3 行使期末合计相符
        single = [i for i, r in enumerate(rows) if len(r["amounts"]) <= per and not r["later"]]
        found = None
        for size in (1, 2, 3):
            found = next((c for c in combinations(single, size)
                          if abs(sum(v for j, v in enumerate(vals) if j not in c) - target) <= tol), None)
            if found:
                break
        if found is None:
            # 行名不在词表里的行（「兖煤澳大利亚有限公司净资产」「改制专户的各项资产」）被并进上一行的原因：
            # 原因里「中文 + 金额」的片段逐个当作一行，取 1～4 个使期末合计相符（容差收紧到 0.1%），这些行不作现金类
            embedded = []
            for r in rows:
                for g in re.finditer(r"[\u4e00-\u9fa5][^⟦]{1,60}?((?:⟦\d+⟧)+)", r["raw"]):
                    ids = [int(i) for i in re.findall(r"⟦(\d+)⟧", g.group(1))]
                    embedded.append(values[ids[per - 1]] if len(ids) >= per else values[ids[0]])
            missing, tight = target - sum(vals), max(0.001 * abs(target), 1.0)
            hit = None
            for size in (1, 2, 3, 4):
                hit = next((c for c in combinations(range(len(embedded)), size)
                            if abs(sum(embedded[i] for i in c) - missing) <= tight), None) if len(embedded) <= 40 else None
                if hit:
                    break
            if hit is not None:
                found, rescued = (), True
        if found is None:
            return dict(status="rows_mismatch", total=target * unit,
                        rows=[(r["label"], v * unit, r["reason"][:60]) for r, v in zip(rows, vals)])
        excluded = set(found)
    footnotes = {}
    for fm in re.finditer(r"注(\d+)[:：](.*?)(?=注\d+[:：]|$)", after):
        footnotes[fm.group(1)] = re.sub(r"⟦\d+⟧", " ", fm.group(2))[:600]
    out_rows = []
    for i, (r, v) in enumerate(zip(rows, vals)):
        if i in excluded:
            continue
        reason = r["reason"]
        for ref in re.findall(r"注(\d+)", reason):
            reason += "｜" + footnotes.get(ref, "")
        out_rows.append(dict(label=r["label"], value=v * unit, reason=reason))
    return dict(status="ok", total=target * unit, rows=out_rows, rescued=rescued)


def classify(rows: list[dict], task: dict, note_cash: dict) -> dict:
    """现金类行按原因分三类；附注三行以核定现金为限，报表行以行值为限。"""
    cash_like = counted = generic = loan = 0.0
    items = []
    for r in rows:
        if r["label"] not in CASH_ITEMS or r["value"] <= 0:
            continue
        cap = None
        if r["label"] in NOTE_LINES:
            cap = note_cash.get((task["code"], task["year"], NOTE_LINES[r["label"]]), 0.0)
        elif r["label"] in BALANCE_FIELD:
            cap = task["balance"].get(BALANCE_FIELD[r["label"]]) or None
        value = min(r["value"], cap) if cap is not None else r["value"]
        cat = "notes" if NOTES_REASON.search(r["reason"]) else "loan" if LOAN_REASON.search(r["reason"]) else "generic"
        cash_like += value
        counted += value if cat == "notes" else 0.0
        generic += value if cat == "generic" else 0.0
        loan += value if cat == "loan" else 0.0
        items.append(f"{r['label']}:{value:.2f}:{cat}")
    return dict(cash_like=cash_like, counted=counted, generic=generic, loan=loan, items=";".join(items))


def parse_task(task: dict, meta: dict, note_cash: dict) -> dict:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    day = re.search(r"finalpage/(\d{4}-\d{2}-\d{2})/", meta.get("url", ""))
    row = dict(security_code=task["code"], security_name=task["name"], fiscal_year=task["year"],
               report_date=task["report_date"], notes_payable=f"{task['notes_payable']:.2f}", extracted_at_utc=stamp,
               announcement_date=day.group(1) if day else meta.get("date", ""), title=meta.get("title", ""),
               url=meta.get("url", ""), counted_yuan="0.00")
    if meta.get("status") != "ok":
        return dict(row, status=meta.get("status", "missing"))
    text = gzip.decompress((cn.CACHE / task["code"] / f"{task['year']}.txt.gz").read_bytes()).decode("utf-8")
    found = find_section(text)
    if found is None:
        return dict(row, status="none_stated" if NONE_STATED.search(re.sub(r"\s+", "", text)) else "section_not_found")
    body, source = found
    if re.match(r"[:：]?(?:□适用)?√?不适用|[:：]?无[。；;]?(?:$|[^\u4e00-\u9fa5])", re.sub(r"\s+", "", body)):
        return dict(row, source=source, status="none_stated")
    parsed = parse_section(body, cash_note=source == "cash_note")
    if parsed["status"] != "ok":
        return dict(row, source=source, status=parsed["status"],
                    restricted_total=f"{parsed['total']:.2f}" if parsed.get("total") is not None else "")
    c = classify(parsed["rows"], task, note_cash)
    return dict(row, source=source + ("+rescue" if parsed.get("rescued") else ""), status="ok", restricted_total=f"{parsed['total']:.2f}",
                cash_like_yuan=f"{c['cash_like']:.2f}", counted_yuan=f"{c['counted']:.2f}",
                generic_yuan=f"{c['generic']:.2f}", loan_only_yuan=f"{c['loan']:.2f}", items=c["items"])


def load_existing() -> dict[tuple[str, int], dict]:
    out = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                out[(r["security_code"], int(r["fiscal_year"]))] = r
    return out


def write(merged: dict) -> None:
    rows = sorted(merged.values(), key=lambda r: (r["security_code"], int(r["fiscal_year"])))
    tmp = OUT.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(OUT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--codes", help="逗号分隔")
    parser.add_argument("--years", help="逗号分隔财年")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="重下原文")
    parser.add_argument("--parse-only", action="store_true", help="只用已缓存文本解析，不联网")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--show", action="store_true", help="打印逐行解析结果（调试）")
    args = parser.parse_args()
    codes = {c.strip().zfill(6) for c in args.codes.split(",")} if args.codes else None
    years = {int(y) for y in args.years.split(",")} if args.years else None
    tasks = plan(codes, years)
    print(f"清单 {len(tasks)} 份年报（{len({t['code'] for t in tasks})} 家）", flush=True)
    if args.plan:
        return 0
    metas: dict[tuple[str, int], dict] = {}
    if not args.parse_only:
        orgs_path = cn.CACHE / "orgid.json"
        orgs = json.loads(orgs_path.read_text()) if orgs_path.exists() else {}
        for code in sorted({t["code"] for t in tasks}):
            try:
                cn.org_id(code, orgs)
            except Exception as exc:                          # noqa: BLE001
                print(f"  ⚠ {code} orgId 失败：{exc}", flush=True)
        orgs_path.write_text(json.dumps(orgs, ensure_ascii=False, indent=0))
        todo = [t for t in tasks if t["code"] in orgs]
        for i, t in enumerate(todo, 1):                      # 串行定位（检索接口限流）
            before = (cn.CACHE / t["code"] / f"{t['year']}.json").exists()
            metas[(t["code"], t["year"])] = cn.locate(t, orgs, args.refresh)
            if not before:
                time.sleep(0.3)
            if i % 200 == 0 or i == len(todo):
                print(f"  定位 {i}/{len(todo)}", flush=True)
        pending = [t for t in todo if metas[(t["code"], t["year"])].get("status") == "located"
                   or (args.refresh and metas[(t["code"], t["year"])].get("status") == "ok")]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(cn.fetch_report, t, metas[(t["code"], t["year"])], args.refresh): t for t in pending}
            for i, fut in enumerate(as_completed(futures), 1):
                t = futures[fut]
                metas[(t["code"], t["year"])] = fut.result()
                if i % 100 == 0 or i == len(pending):
                    print(f"  下载 {i}/{len(pending)}", flush=True)
    for t in tasks:
        path = cn.CACHE / t["code"] / f"{t['year']}.json"
        if (t["code"], t["year"]) not in metas:
            metas[(t["code"], t["year"])] = json.loads(path.read_text()) if path.exists() else dict(status="not_fetched")
    note_cash = load_note_cash()
    results = {}
    for t in tasks:
        meta = metas[(t["code"], t["year"])]
        results[(t["code"], t["year"])] = parse_task(t, meta, note_cash)
        if args.show and meta.get("status") == "ok":
            text = gzip.decompress((cn.CACHE / t["code"] / f"{t['year']}.txt.gz").read_bytes()).decode("utf-8")
            found = find_section(text)
            print(t["code"], t["year"], json.dumps(parse_section(found[0], found[1] == "cash_note") if found else None,
                                                   ensure_ascii=False, indent=1))
    merged = {**load_existing(), **results}
    write(merged)
    stats: dict[str, int] = {}
    for r in results.values():
        key = (r.get("status") or "").split(":")[0]
        stats[key] = stats.get(key, 0) + 1
    ok = [r for r in results.values() if r.get("status") == "ok"]
    print(f"状态：{stats}")
    print(f"核定 {len(ok)} 份：计入 {sum(cn._num(r['counted_yuan']) for r in ok) / 1e8:.1f} 亿，"
          f"笼统原因 {sum(cn._num(r['generic_yuan']) for r in ok) / 1e8:.1f} 亿，只写借款 {sum(cn._num(r['loan_only_yuan']) for r in ok) / 1e8:.1f} 亿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

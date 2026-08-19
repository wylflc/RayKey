#!/usr/bin/env python3
"""三大报表全量历史（逐公司年报），为 ROIC/FCFF 真口径估值提供输入。

为什么需要它
------------
`fetch_a_share_quarterly_financials.py` 取的是东财**业绩报表** `RPT_LICO_FN_CPD`，
只有归母净利／营收／EPS／BPS／ROE／毛利率／每股经营现金流八类摘要指标。
用它实现「All Money Is Equal」框架时（§12.65），`NOPAT`／`投入资本`／`FCFF`／`ROIC`／
**维持性资本开支**／`ΔWC` 全部算不出来，只能拿经营现金流当 Owner Earnings 的代理——
而经营现金流**加回了折旧摊销却没扣资本开支**，对重资产公司系统性偏高。
实测该偏差逐一体现在持仓上（神火 +4.9pp、中石油 +4.5pp、陕煤 +4.4pp vs 银行/消费被砍），
故 §12.65 的结论只能是「没测出按现金比较是否更好，测出的是把折旧当成现金会怎样」。
本表补齐那个缺口（OI-060）。

数据源
------
东财 F10 三大报表（`datacenter.eastmoney.com/securities/api/data/v1/get`，`source=HSF10`），
与 `fetch_a_share_quarterly_financials.py` 同为东财公开接口、**无需任何凭据**。
按 `ORG_TYPE` 分四套表：通用 `G*`／银行 `B*`／券商 `S*`／保险 `I*`，
本脚本按 G→B→S→I 顺序试探并记下命中的那套（`org_table` 列）。

实测覆盖：一次请求即返回该股**全部年报期**（茅台 26 期回到 2000、格力 28 期回到 1998、
海螺 27 期回到 1999），故 211 只 × 3 张表 ≈ 633 次请求。

`NOTICE_DATE` 与 §12.4 前视约束
-------------------------------
与业绩报表同规：`available_at` 必须是**公告日**而非报告期末，故逐行落 `notice_date`。
另落 `update_date`——东财在追溯重述后会改该字段，下游若要复核「这一版是不是当年那一版」
需要它（本表不做取舍，只如实记录）。

**不做无差别 ALL 落盘的例外**：本脚本保留全部非 `_YOY` 列。理由是四套表的列名互不相同
（银行有 `ACCEPT_DEPOSIT`／`LOAN_ADVANCE`，通用表没有），手工枚举四套白名单必然
**静默漏掉银行的关键列**；而本表只覆盖面板 211 只、年报约 5,000 行，落全列也只有个位数 MB。
`_YOY` 列是纯派生（同比率），一律丢弃。

用法::

    python3 scripts/fetch_a_share_financial_statements.py --panel data/processed/pit_attention/panel_moat_bank_v5.csv
    python3 scripts/fetch_a_share_financial_statements.py --codes 600519 601166 --refresh
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/raw/financials_statements"
PANEL = ROOT / "data/processed/pit_attention/panel_moat_bank_v5.csv"
API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
HEADERS = {"User-Agent": "Mozilla/5.0",
           "Referer": "https://emweb.securities.eastmoney.com/"}

# 三张表 × 四套口径。按此顺序试探，先命中先用。
STATEMENTS = {
    "balance": ("RPT_F10_FINANCE_GBALANCE", "RPT_F10_FINANCE_BBALANCE",
                "RPT_F10_FINANCE_SBALANCE", "RPT_F10_FINANCE_IBALANCE"),
    "income": ("RPT_F10_FINANCE_GINCOME", "RPT_F10_FINANCE_BINCOME",
               "RPT_F10_FINANCE_SINCOME", "RPT_F10_FINANCE_IINCOME"),
    "cashflow": ("RPT_F10_FINANCE_GCASHFLOW", "RPT_F10_FINANCE_BCASHFLOW",
                 "RPT_F10_FINANCE_SCASHFLOW", "RPT_F10_FINANCE_ICASHFLOW"),
}

# §12.65 判定 ROIC/FCFF 可算所必须的列——取数后逐列自检，缺哪列直接说，不静默降级。
REQUIRED = {
    "balance": ("TOTAL_ASSETS", "TOTAL_EQUITY", "TOTAL_PARENT_EQUITY", "MONETARYFUNDS"),
    "income": ("OPERATE_PROFIT", "TOTAL_PROFIT", "INCOME_TAX", "PARENT_NETPROFIT"),
    "cashflow": ("NETCASH_OPERATE", "CONSTRUCT_LONG_ASSET", "FA_IR_DEPR"),
}


def secucode(code: str) -> str:
    """六位代码 → 东财 `SECUCODE`。面板实测只有沪深两市。"""
    code = code.zfill(6)
    if code[0] in "69":
        return f"{code}.SH"
    if code[0] in "03":
        return f"{code}.SZ"
    return f"{code}.BJ"


def fetch(report_name: str, code: str, timeout: float) -> tuple[list[dict], str | None]:
    """取某股某表的**全部年报期**。一页取尽（实测最多 28 期，远小于 pageSize）。"""
    query = urllib.parse.urlencode({
        "reportName": report_name, "columns": "ALL",
        "filter": f'(SECUCODE="{secucode(code)}")(REPORT_TYPE="年报")',
        "pageNumber": "1", "pageSize": "200",
        "sortTypes": "-1", "sortColumns": "REPORT_DATE",
        "source": "HSF10", "client": "PC",
    })
    request = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return [], f"{type(exc).__name__}"
    result = payload.get("result") or {}
    return (result.get("data") or []), None


def normalise(rows: list[dict], code: str, table: str) -> list[dict]:
    """丢 `_YOY` 派生列、统一日期到 10 位、补审计与来源字段。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = []
    for item in rows:
        row = {k: ("" if v is None else str(v))
               for k, v in item.items() if not k.endswith("_YOY")}
        for key in ("REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE"):
            if key in row:
                row[key] = row[key][:10]
        row["security_code"] = code.zfill(6)
        row["org_table"] = table
        row["source"] = f"eastmoney {table}"
        row["retrieved_at_utc"] = now
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="三大报表全量历史取数（ROIC/FCFF 前置）")
    parser.add_argument("--panel", type=Path, default=PANEL)
    parser.add_argument("--codes", nargs="*", help="只取这些代码，缺省取面板全体")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--refresh", action="store_true", help="重取已有文件")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--pause", type=float, default=0.25)
    args = parser.parse_args()

    if args.codes:
        codes = sorted({c.zfill(6) for c in args.codes})
    else:
        with args.panel.open(encoding="utf-8-sig") as handle:
            codes = sorted({r["security_code"].zfill(6) for r in csv.DictReader(handle)})
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"三大报表取数：{len(codes)} 只 × {len(STATEMENTS)} 张表｜"
          f"落点 {args.out_dir if args.out_dir.is_absolute() and ROOT not in args.out_dir.parents else args.out_dir.relative_to(ROOT)}/")

    failures: list[str] = []
    tables_used: dict[str, int] = {}
    for kind, candidates in STATEMENTS.items():
        path = args.out_dir / f"{kind}.csv"
        if path.exists() and not args.refresh:
            print(f"  {kind}: 已存在，跳过（--refresh 重取）")
            continue
        all_rows: list[dict] = []
        for index, code in enumerate(codes, start=1):
            rows: list[dict] = []
            for table in candidates:
                got, error = fetch(table, code, args.timeout)
                if error:
                    failures.append(f"{code}/{table}：{error}")
                    continue
                if got:
                    rows = normalise(got, code, table)
                    tables_used[f"{kind}:{table}"] = tables_used.get(f"{kind}:{table}", 0) + 1
                    break
                time.sleep(args.pause)
            if not rows:
                failures.append(f"{code}/{kind}：**四套表全空**")
            all_rows.extend(rows)
            if index % 25 == 0:
                print(f"    {kind} {index}/{len(codes)}｜累计 {len(all_rows):,} 行")
            time.sleep(args.pause)

        if not all_rows:
            failures.append(f"{kind}：**0 行**，不落盘")
            continue
        fields: list[str] = []
        for row in all_rows:                       # 四套表列名不同，取并集且保序
            for key in row:
                if key not in fields:
                    fields.append(key)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, restval="")
            writer.writeheader()
            writer.writerows(all_rows)
        got_codes = len({r["security_code"] for r in all_rows})
        print(f"  {kind}: {len(all_rows):,} 行、{got_codes}/{len(codes)} 只、{len(fields)} 列 → {path.name}")

        # §13 第 3 条：新增数据源须核对非空行数与关键列覆盖
        print(f"    关键列非空覆盖：", end="")
        for field in REQUIRED[kind]:
            filled = sum(1 for r in all_rows if (r.get(field) or "").strip())
            print(f"{field}={filled}/{len(all_rows)}  ", end="")
        print()
        no_notice = sum(1 for r in all_rows if not (r.get("NOTICE_DATE") or "").strip())
        if no_notice:
            print(f"    ⚠ **{no_notice} 行无公告日**——这些行不可用于历史建带（§12.4）")

    if tables_used:
        print("\n命中表口径：" + "｜".join(f"{k}×{v}" for k, v in sorted(tables_used.items())))
    if failures:
        print(f"\n**失败 {len(failures)} 项**：{'；'.join(failures[:12])}"
              + ("…" if len(failures) > 12 else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

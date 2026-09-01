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
**静默漏掉银行的关键列**；而本表只覆盖回测宇宙与分层表数百只、年报数千行，落全列也只有个位数 MB。
`_YOY` 列是纯派生（同比率），一律丢弃。

增量规则（OI-098）
------------------
`--signal-date` 是信号日，证据日统一取下一工作日。**应到年报期** = 证据日上一年的 12-31。
名单里的代码分三类处理：①文件里没有的→取；②文件里有、但最新 `REPORT_DATE` 早于应到年报期
→ **整只重取并替换**（东财一次返回全部年报期，替换即超集）；③已到应到期→跳过。
2026-08-24 前只有 ①，「代码已在文件里」就整只跳过——年报披露后按 §6.7 命令跑，已有的
333 只永远停在首次抓取时的最新年报，三表估值输入静默过期（与逐季脚本的披露窗强制重取同一缺陷类）。
重取失败（网络或四套表全空）时保留该代码原有行，不丢数据；重取后仍未到应到期的（尚未披露）
逐次运行都会再试，直到披露。`--refresh` 仍是全量重取。

**追溯重述探针（OI-126）**：已在库且年报期已到的代码不再直接跳过——每次都重取其资产负债表
（一只一请求，兼作探针），逐期比 `UPDATE_DATE`：远端任一期比本地新即判「重述」，该代码三张表
整只替换；未变的保留本地行不动。判例：电投能源（002128）2026-06-03 同一控制下合并后，东财把
FY2025 归母权益 381.9982 亿追溯重述为 471.7883 亿、`UPDATE_DATE` 2026-04-15→2026-08-26，
旧判据「最新年报期已到即跳过」让它永远进不来。`--no-probe` 关闭探针（只在明确不需要时用）。

用法::

    python3 scripts/fetch_a_share_financial_statements.py --signal-date 2026-08-24
    python3 scripts/fetch_a_share_financial_statements.py --panel data/processed/pit_attention/panel_moat_bank_v6b.csv
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
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
from a_share_signal_dates import evidence_date_for_signal

OUT_DIR = ROOT / "data/raw/financials_statements"
PANELS = (ROOT / "data/processed/pit_attention/panel_moat_bank_v6b.csv",
          ROOT / "data/processed/a_share_watchlist_quality_tiers.csv")
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
# OI-126 重述日志：探针检出 UPDATE_DATE 变化时，这些字段变动 ≥ RESTATE_MIN_CHANGE 才记为「关键值实变」
RESTATE_FIELDS = ("TOTAL_PARENT_EQUITY", "TOTAL_EQUITY", "TOTAL_ASSETS", "SHARE_CAPITAL", "MONETARYFUNDS", "MINORITY_EQUITY")
RESTATE_MIN_CHANGE = 0.005
RESTATE_LOG = ROOT / "data/interim/statement_restatements.csv"
COVERAGE_GAP_LOG = ROOT / "data/interim/statement_coverage_gaps.csv"
COVERAGE_MIN_YEARS = 3           # 与建带器 --min-roe-years 缺省一致，少于此数建带必拒


REQUIRED = {
    "balance": ("TOTAL_ASSETS", "TOTAL_EQUITY", "TOTAL_PARENT_EQUITY", "MONETARYFUNDS"),
    "income": ("OPERATE_PROFIT", "TOTAL_PROFIT", "INCOME_TAX", "PARENT_NETPROFIT"),
    "cashflow": ("NETCASH_OPERATE", "CONSTRUCT_LONG_ASSET", "FA_IR_DEPR"),
}


def secucode(code: str) -> str:
    """六位代码 → 东财 `SECUCODE`。北交所 `920xxx`（及 43/83/87/88 段）用 `.BJ`，`9` 开头的沪市只有 B 股 `900xxx`。"""
    code = code.zfill(6)
    if code.startswith("92"):
        return f"{code}.BJ"
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


def beijing_today() -> date:
    """证据日缺省：北京历日（本机时区不是北京，不能用 `date.today()`）。"""
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def expected_annual_period(as_of: date) -> str:
    """`as-of` 时点应到的最新年报期末 = 上一年 12-31（年报披露窗自次年 1-1 起开）。"""
    return f"{as_of.year - 1:04d}-12-31"


def plan_codes(existing_rows: list[dict], codes: list[str],
               expected_period: str) -> tuple[list[str], list[str]]:
    """把名单分成「文件里没有的」与「有但最新年报期早于应到期的」两组，各按名单顺序。"""
    latest = latest_period_by_code(existing_rows)
    missing = [c for c in codes if c not in latest]
    stale = [c for c in codes if c in latest and latest[c] < expected_period]
    return missing, stale


def latest_period_by_code(rows: list[dict]) -> dict[str, str]:
    """代码 → 该代码在行集里的最新 `REPORT_DATE`（无日期的行记空串，代码仍计入）。"""
    out: dict[str, str] = {}
    for row in rows:
        code = (row.get("security_code") or "").zfill(6)
        period = (row.get("REPORT_DATE") or "")[:10]
        if period >= out.get(code, ""):
            out[code] = period
    return out


def periods_by_code(rows: list[dict]) -> dict[str, int]:
    """代码 → 该代码在行集里不同 `REPORT_DATE` 的个数（判三大报表覆盖是否够建带）。"""
    seen: dict[str, set[str]] = {}
    for row in rows:
        code = (row.get("security_code") or "").zfill(6)
        period = (row.get("REPORT_DATE") or "")[:10]
        if code and period:
            seen.setdefault(code, set()).add(period)
    return {c: len(p) for c, p in seen.items()}


def coverage_gaps(codes: list[str], coverage: dict[str, dict[str, int]],
                  min_years: int) -> list[dict]:
    """名单里三大报表覆盖不足以建 ROIC 带的代码。

    建带器对这两种缺口的行为不同：三张表任一为 0 行 → `code not in ROIC_YEARS` → **静默退回
    权益口径**（回测没有这个估值模式，产出的带不可用于决策）；年报期数不足 → 明确 `rejected`。
    两者都在这里报，前者是必须处置的告警。"""
    gaps = []
    for code in codes:
        missing = [k for k in STATEMENTS if not coverage.get(k, {}).get(code)]
        years = min((coverage.get(k, {}).get(code, 0) for k in STATEMENTS), default=0)
        if missing:
            gaps.append({"security_code": code, "gap": "无报表",
                         "detail": f"缺表 {'/'.join(missing)}", "annual_periods": years,
                         "band_effect": "建带静默退回权益口径"})
        elif years < min_years:
            gaps.append({"security_code": code, "gap": "年报期不足",
                         "detail": f"最少一张表仅 {years} 期 < {min_years}", "annual_periods": years,
                         "band_effect": "建带 rejected"})
    return gaps


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
    parser.add_argument("--panel", type=Path, nargs="+", default=list(PANELS),
                        help="取这些名单文件里 security_code 的并集，缺省＝回测宇宙 ∪ 分层表")
    parser.add_argument("--codes", nargs="*", help="只取这些代码，缺省取面板全体")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--signal-date", type=date.fromisoformat, required=True,
                        help="信号日 YYYY-MM-DD；证据日自动取下一工作日")
    parser.add_argument("--refresh", action="store_true", help="全量重取（含已到应到年报期的代码）")
    parser.add_argument("--no-probe", action="store_true",
                        help="关闭追溯重述探针（缺省对已在库代码重取资产负债表比 UPDATE_DATE）")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--pause", type=float, default=0.25)
    args = parser.parse_args()
    as_of = evidence_date_for_signal(args.signal_date)
    expected = expected_annual_period(as_of)

    if args.codes:
        codes = sorted({c.zfill(6) for c in args.codes})
    else:
        codes = set()
        for panel in args.panel:
            with panel.open(encoding="utf-8-sig") as handle:
                codes |= {r["security_code"].zfill(6) for r in csv.DictReader(handle)}
        codes = sorted(codes)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"三大报表取数：{len(codes)} 只 × {len(STATEMENTS)} 张表｜as-of {as_of}（应到年报期 {expected}）｜"
          f"落点 {args.out_dir if args.out_dir.is_absolute() and ROOT not in args.out_dir.parents else args.out_dir.relative_to(ROOT)}/")

    failures: list[str] = []
    coverage: dict[str, dict[str, int]] = {}   # 表 → {代码: 年报期数}
    tables_used: dict[str, int] = {}
    restated: dict[str, list[str]] = {}          # 探针检出重述的代码 → 变了的报告期（OI-126）
    restate_log: list[dict] = []                 # 关键值实变的 (代码, 期, 字段)
    probe_unchanged = 0
    probe_failed = 0
    for kind, candidates in STATEMENTS.items():
        path = args.out_dir / f"{kind}.csv"
        existing_rows: list[dict] = []
        todo = list(codes)
        stale: list[str] = []
        probe: set[str] = set()
        if path.exists() and not args.refresh:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                existing_rows = list(csv.DictReader(handle))
            missing, stale = plan_codes(existing_rows, codes, expected)
            todo = missing + stale
            settled = [c for c in codes if c not in missing and c not in stale]
            if kind == "balance" and not args.no_probe:
                probe = set(settled)                  # 资产负债表全取，兼作重述探针
                todo = todo + settled
            elif kind != "balance":
                todo = todo + [c for c in settled if c in restated]
            if not todo:
                coverage[kind] = periods_by_code(existing_rows)
                print(f"  {kind}: 名单 {len(codes)} 只已全部在库且年报期到 {expected}，跳过（--refresh 全量重取）")
                continue
            have = len(latest_period_by_code(existing_rows))
            print(f"  {kind}: 已有 {have} 只，新增补取 {len(missing)} 只、年报期落后 {expected} 重取 {len(stale)} 只"
                  + (f"、重述探针 {len(probe)} 只" if probe else "")
                  + (f"、探针检出重述重取 {len([c for c in todo if c in restated])} 只" if kind != "balance" and restated else ""))
        local_update: dict[str, dict[str, str]] = {}
        if probe:
            for row in existing_rows:
                code = (row.get("security_code") or "").zfill(6)
                if code in probe:
                    local_update.setdefault(code, {})[(row.get("REPORT_DATE") or "")[:10]] = (row.get("UPDATE_DATE") or "")[:10]
        fetched: dict[str, list[dict]] = {}          # 取到行的代码 → 全部年报期（替换其旧行）
        for index, code in enumerate(todo, start=1):
            rows: list[dict] = []
            errors: list[str] = []
            for table in candidates:
                got, error = fetch(table, code, args.timeout)
                if error:
                    errors.append(f"{code}/{table}：{error}")
                    continue
                if got:
                    rows = normalise(got, code, table)
                    tables_used[f"{kind}:{table}"] = tables_used.get(f"{kind}:{table}", 0) + 1
                    break
                time.sleep(args.pause)
            if code in probe and not rows:
                # 探针取不到（网络或空表）：保留本地行、不计失败——与加探针前「已到期即跳过」的结果一致，只在汇总里报数
                probe_failed += 1
                time.sleep(args.pause)
                continue
            failures.extend(errors)
            if rows and code in probe:
                # 探针：逐期比 UPDATE_DATE，远端任一期更新即判重述；未变则保留本地行不替换
                local = local_update.get(code, {})
                remote = {(r.get("REPORT_DATE") or "")[:10]: (r.get("UPDATE_DATE") or "")[:10] for r in rows}
                changed = sorted(p for p, u in remote.items() if u > local.get(p, ""))
                if changed:
                    restated[code] = changed
                    # 关键值实变的期写入重述日志（OI-126）：只碰日期不改值的不记，下游检查⑥只看这里
                    old_rows = {(r.get("REPORT_DATE") or "")[:10]: r for r in existing_rows
                                if (r.get("security_code") or "").zfill(6) == code}
                    for r in rows:
                        per = (r.get("REPORT_DATE") or "")[:10]
                        if per not in changed or per not in old_rows:
                            continue
                        for field in RESTATE_FIELDS:
                            try:
                                a, b = float(old_rows[per].get(field) or "nan"), float(r.get(field) or "nan")
                            except ValueError:
                                continue
                            if a == a and b == b and a != 0 and abs(b / a - 1) >= RESTATE_MIN_CHANGE:
                                restate_log.append({
                                    "security_code": code, "report_date": per, "field": field,
                                    "old_value": f"{a:.2f}", "new_value": f"{b:.2f}", "change_pct": f"{(b / a - 1) * 100:.2f}",
                                    "old_update_date": local.get(per, ""), "new_update_date": remote[per],
                                    "detected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                })
                else:
                    probe_unchanged += 1
                    rows = []
                    if index % 25 == 0:
                        print(f"    {kind} {index}/{len(todo)}｜探针未变 {probe_unchanged}｜重述 {len(restated)}")
                    time.sleep(args.pause)
                    continue
            if rows:
                fetched[code] = rows
            else:
                failures.append(f"{code}/{kind}：**四套表全空**" + ("，保留原有行" if code in stale else ""))
            if index % 25 == 0:
                print(f"    {kind} {index}/{len(todo)}｜取到 {sum(len(v) for v in fetched.values()):,} 行"
                      + (f"｜探针未变 {probe_unchanged}｜重述 {len(restated)}" if probe else ""))
            time.sleep(args.pause)
        if probe:
            print(f"    重述探针：{len(probe)} 只在库，UPDATE_DATE 未变 {probe_unchanged} 只，**检出重述 {len(restated)} 只**"
                  + (f"，取不到保留本地 {probe_failed} 只" if probe_failed else "")
                  + ("：" + "；".join(f"{c}({','.join(p[:4] for p in ps)})" for c, ps in sorted(restated.items())[:20])
                     + ("…" if len(restated) > 20 else "") if restated else ""))

        # 合并：重取成功的代码整只替换（超集），失败的保留原有行；新代码追加。
        all_rows: list[dict] = [r for r in existing_rows
                                if (r.get("security_code") or "").zfill(6) not in fetched]
        for code in todo:
            all_rows.extend(fetched.get(code, []))
        if stale:
            after = latest_period_by_code(all_rows)
            behind = [c for c in stale if after.get(c, "") < expected]
            print(f"    年报期落后重取 {len(stale)} 只：补到 {expected} 的 {len(stale) - len(behind)} 只"
                  + (f"，仍未到（尚未披露或取数失败）{len(behind)} 只：{' '.join(behind[:12])}"
                     + ("…" if len(behind) > 12 else "") if behind else ""))

        if not all_rows:
            coverage[kind] = {}
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
        coverage[kind] = periods_by_code(all_rows)
        print(f"  {kind}: {len(all_rows):,} 行、{got_codes} 只（名单 {len(codes)}）、{len(fields)} 列 → {path.name}")

        # §13 第 3 条：新增数据源须核对非空行数与关键列覆盖
        print(f"    关键列非空覆盖：", end="")
        for field in REQUIRED[kind]:
            filled = sum(1 for r in all_rows if (r.get(field) or "").strip())
            print(f"{field}={filled}/{len(all_rows)}  ", end="")
        print()
        no_notice = sum(1 for r in all_rows if not (r.get("NOTICE_DATE") or "").strip())
        if no_notice:
            print(f"    ⚠ **{no_notice} 行无公告日**——这些行不可用于历史建带（§12.4）")

    if restate_log:
        RESTATE_LOG.parent.mkdir(parents=True, exist_ok=True)
        exists = RESTATE_LOG.exists()
        with RESTATE_LOG.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(restate_log[0].keys()))
            if not exists:
                writer.writeheader()
            writer.writerows(restate_log)
        by_code = {}
        for r in restate_log:
            by_code.setdefault(r["security_code"], set()).add(r["report_date"])
        print(f"\n**重述日志**：关键值实变 {len(restate_log)} 项、{len(by_code)} 只 → {RESTATE_LOG.relative_to(ROOT) if ROOT in RESTATE_LOG.parents else RESTATE_LOG}"
              f"（追加）：" + "；".join(f"{c}({','.join(sorted(p)[:3])})" for c, p in sorted(by_code.items())[:15])
              + ("…" if len(by_code) > 15 else ""))

    if tables_used:
        print("\n命中表口径：" + "｜".join(f"{k}×{v}" for k, v in sorted(tables_used.items())))

    gaps = coverage_gaps(codes, coverage, COVERAGE_MIN_YEARS) if coverage else []
    rel = COVERAGE_GAP_LOG.relative_to(ROOT) if ROOT in COVERAGE_GAP_LOG.parents else COVERAGE_GAP_LOG
    COVERAGE_GAP_LOG.parent.mkdir(parents=True, exist_ok=True)
    with COVERAGE_GAP_LOG.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["security_code", "gap", "detail",
                                                    "annual_periods", "band_effect", "checked_at"])
        writer.writeheader()
        for row in gaps:
            writer.writerow({**row, "checked_at": as_of.isoformat()})
    if gaps:
        silent = [g for g in gaps if g["gap"] == "无报表"]
        print(f"\n⚠ **三大报表覆盖缺口 {len(gaps)} 只**（名单 {len(codes)} 只）→ {rel}")
        for row in gaps[:20]:
            print(f"    {row['security_code']}  {row['gap']}：{row['detail']}　→ {row['band_effect']}")
        if len(gaps) > 20:
            print(f"    …另 {len(gaps) - 20} 只见文件")
        if silent:
            print(f"  **{len(silent)} 只无报表**：这些代码建带会退回权益口径，回测没有该估值模式，"
                  f"其带不得用于决策。须补取或登记 open issue 后再继续 §6.7。")
    else:
        print(f"\n三大报表覆盖：名单 {len(codes)} 只全部三表齐备且年报期 ≥ {COVERAGE_MIN_YEARS} → {rel}（空）")

    if failures:
        print(f"\n**失败 {len(failures)} 项**：{'；'.join(failures[:12])}"
              + ("…" if len(failures) > 12 else ""))
    return 1 if (failures or gaps) else 0


if __name__ == "__main__":
    raise SystemExit(main())

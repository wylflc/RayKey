#!/usr/bin/env python3
"""海外关注清单的财报日历与「复核逾期」自检（§6.8 复核触发①，结 OI-039）。

为什么要有这个脚本
------------------
§6.8 复核触发① 规定「各公司财报日已知者写入 `notes`，披露次日按 §7.3/§7.5.5 复核带与
档」——但**这条触发的全部载体是一个自由文本字段**：海外行既没有 A 股那样的披露物化文件
（§6.7.8/§6.7.9），也不进 §9.1 第一步 1a 的机械覆盖（§6.8 边界第 2 条明文排除）。
**后果是漏做不会被任何环节发现。**

实测判例（2026-08-07）：苹果 `notes` 原文写着「FY2026Q3 财报 2026-07-30 公布，次日须复核」、
三星电子写着「完整财报 2026-07-30，次日须复核」——两条都在各自那一行上，而 08-03 建档批与
08-06 扩表批**都没有人去读它**，各逾期 8 天；同期迪士尼与优步（均 08-05 披露）欠账 2 天。
这不是执行疏忽，是机制缺位：`evidence_available_at` 与下期财报日本就构成可比对的两端，
但没有任何代码做这个比对。

用户 2026-08-07 裁定按「接入海外财报日历数据源」修（三个方向中的第③个，明确同意为此
新增外部数据源）。本脚本即该数据源的接入点。

数据源与其覆盖边界（**必须连边界一起读**）
------------------------------------------
* **美股：Nasdaq 财报日历** `api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`，
  无密钥、按日查询，返回当日全部披露公司。实测 2026-08-07 连续 10 日全部 200。
* **向后扫描才是本缺陷的解药，向前只是附赠**。实测：向前 150 天只命中 5/18 家美股——
  大市值公司的下期财报日要临近才进该日历（接口自己回「Zacks 尚未提供」）；而**向后**
  120 天可逐一还原已发生的披露日，实测 AAPL 2026-07-30、DIS/UBER 2026-08-05、
  MSFT/META 2026-07-29、AMD 2026-08-04，与登记 OI-039 时人工核出的日期完全一致。
  OI-039 的失效形态是「**报告已经出来了而没人复核**」，判定它需要的是**已披露日**，
  不是预告日。故 `last_report_date` 是主判据，`next_report_date` 只作提前量提示。
  这与 A 股侧 §7.3「公告日 > 复核日即入队」是同一个机制，本脚本是它的海外对应物。
* **同一公司的另一上市线可作代理**：清单按 §6.8 边界第 5 条以「实际定价用的那条线」
  建行（阿里/京东取港股线），但**财报是公司层面的事件、两条线同日**，故其美股 ADR
  代码可直接作财报日代理（09988→BABA、09618→JD）。这不改变定价线，只借日期。
* **其余港股与韩股：无可用的免密钥日历源**。已实测东财 F10 的港美股财务接口只给报告
  期末（`REPORT_DATE`）**不含公告日**，东财港股公告接口对本清单返回 0 行；港交所与
  KRX 的业绩时间表无稳定的结构化免密钥接口。故腾讯/泡泡玛特/美团/海底捞/三星电子/
  SK海力士共 6 行**仍为人工维护**，本脚本不覆盖、也不假装覆盖——`--apply` 只写它确实
  查到的行，其余保持原值，并在末尾把「无财报日的行」逐行列出（§15.2 第 3 条：任何
  未覆盖都必须可见，不得静默）。

产出与自检
----------
1. `data/interim/overseas_earnings_calendar.csv`——扫描窗口内查到的逐票财报日快照。
2. `--apply` 把美股行的 `next_report_date` / `next_report_source` 写回 §6.8 清单。
3. `overdue_reviews()`——**每日跑批时执行的那个检查**：`next_report_date` 已过、而该行
   的复核证据日早于它，即为逾期。由 `build_a_share_core_valuation_pool.py` 在渲染海外
   附表时调用（§9.1 第二步每日必跑），使漏做当天就被喊出来。

用法::

    python3 scripts/fetch_overseas_earnings_calendar.py --as-of 2026-08-07 --days 150
    python3 scripts/fetch_overseas_earnings_calendar.py --as-of 2026-08-07 --apply
    python3 scripts/fetch_overseas_earnings_calendar.py --as-of 2026-08-07 --check-only
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERSEAS_CSV = ROOT / "data/processed/overseas_watchlist_valuation.csv"
CALENDAR_CSV = ROOT / "data/interim/overseas_earnings_calendar.csv"

NASDAQ_API = "https://api.nasdaq.com/api/calendar/earnings?date={day}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Nasdaq 日历用 `BRK/B` 这类斜杠写法，清单里是 `BRK.B`。只有确有差异的才列在这里。
SYMBOL_ALIASES = {"BRK.B": {"BRK/B", "BRK.B"}}

# 同一公司另一上市线的代码，只借财报日、不改定价线（§6.8 边界第 5 条）。
EARNINGS_PROXY = {"09988": "BABA", "09618": "JD"}

CALENDAR_FIELDS = [
    "security_code", "security_name", "market_type",
    "last_report_date", "next_report_date", "report_time", "fiscal_quarter_ending",
    "source", "retrieved_at_utc",
]


def load_overseas(path: Path = OVERSEAS_CSV) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# --------------------------------------------------------------- 日历抓取（美股）
def scan_nasdaq_calendar(as_of: date, back_days: int, fwd_days: int,
                         timeout: float, pause: float) -> dict[str, dict[str, str]]:
    """逐日扫描 [as_of−back_days, as_of+fwd_days]，按标的归并出上一次与下一次财报日。

    逐日查询是该接口唯一的形态（无区间参数）。向后取**最晚的一个 ≤ as_of** 作
    `last_report_date`（主判据），向前取**最早的一个 > as_of** 作 `next_report_date`。
    """
    found: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    for offset in range(-back_days, fwd_days + 1):
        day_date = as_of + timedelta(days=offset)
        day = day_date.isoformat()
        try:
            request = urllib.request.Request(NASDAQ_API.format(day=day), headers=HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            failed.append(day)
            continue
        for row in ((payload.get("data") or {}).get("rows") or []):
            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            entry = found.setdefault(symbol, {"last": "", "next": "", "time": "", "fq": ""})
            if day_date <= as_of:
                if day > entry["last"]:            # 取最晚的已披露日
                    entry["last"] = day
            elif not entry["next"]:                # 首个未来日即下一次
                entry["next"] = day
                entry["time"] = str(row.get("time", "") or "")
                entry["fq"] = str(row.get("fiscalQuarterEnding", "") or "")
        time.sleep(pause)
    if failed:
        # 抓取缺日必须可见：静默跳过会让「今天没查到」与「今天没人报」长得一样（§15.2 第 3 条）。
        print(f"  **日历抓取失败 {len(failed)} 天**（该窗口内这些日期未覆盖）：{'、'.join(failed[:8])}"
              + ("…" if len(failed) > 8 else ""))
    return found


def match_symbol(code: str, found: dict[str, dict[str, str]]) -> dict[str, str] | None:
    candidates = set(SYMBOL_ALIASES.get(code, {code}))
    if code in EARNINGS_PROXY:
        candidates.add(EARNINGS_PROXY[code])
    for candidate in candidates:
        hit = found.get(candidate.upper())
        if hit:
            return hit
    return None


# --------------------------------------------------------------- 逾期自检（每日跑批调用）
def _as_deadline(value: str) -> date | None:
    """把 `next_report_date` 解析成「该日之后即应已披露」的判定日。

    允许两种精度：`YYYY-MM-DD` 用当日；`YYYY-MM` 用**该月最后一天**——月精度的写法（人工
    维护的港韩行常见「约 2026-11」）只在整月过完后才算逾期，宁可晚报不可误报。
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        if len(value) == 7:
            year, month = int(value[:4]), int(value[5:7])
            return date(year, month, calendar.monthrange(year, month)[1])
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _review_evidence_date(row: dict[str, str]) -> date | None:
    """该行的**带所依据的证据日**（`evidence_available_at`）。

    这里刻意**不读** `valuation_reviewed_at`，两个字段回答的是不同的问题：

    * `valuation_reviewed_at` = 我们最后一次**动过这一行**。判例即 OI-039 本身——苹果
      在 2026-08-03 被建档批动过（`valuation_reviewed_at` = 08-03，晚于 07-30 的财报日），
      但那一批**用的是财报前的输入**。拿它作判据会把这次漏做判成「已复核」，正好放过
      本缺陷要抓的那一类。
    * `evidence_available_at` = 带**依据的**最新证据的公开可得日（§7.2 口径）。财报没被
      吸收进带，这个日期就还停在财报之前——它才是与披露日可比的那一端，也正是登记
      OI-039 时点名的「本就构成可比对的两端」。

    附带解掉 v2.15「重跑不等于复核」的残留风险：该规则只在**结论真的变了**时才写
    `valuation_reviewed_at`，故一次真做了、但带与档恰好不变的复核留不下复核日；而
    `evidence_available_at` 由取证动作本身更新，与结论变没变无关，不受该规则影响。

    实测交叉验证（2026-08-07）：Nasdaq 日历还原的披露日与本清单人工维护的
    `evidence_available_at` 在 20 家可覆盖标的上**逐行相等**。
    """
    return _as_deadline(row.get("evidence_available_at", ""))


def overdue_reviews(rows: list[dict[str, str]], as_of: date) -> tuple[list[dict[str, object]], list[dict[str, str]], list[dict[str, str]]]:
    """返回 (逾期未复核清单, 无财报日的行, 今明两日有财报的行)。

    逾期定义：**已披露日**（`last_report_date`，缺失时退回已过期的 `next_report_date`）
    晚于该行最后一次看证据的日期 —— 即报告已经出来了，而我们的带还建在它之前的证据上。
    """
    overdue: list[dict[str, object]] = []
    missing: list[dict[str, str]] = []
    upcoming: list[dict[str, str]] = []

    for row in rows:
        nxt = _as_deadline(row.get("next_report_date", ""))
        if nxt and as_of <= nxt <= as_of + timedelta(days=1):
            upcoming.append(row)

        disclosed = _as_deadline(row.get("last_report_date", ""))
        if disclosed is None and nxt is not None and nxt <= as_of:
            disclosed = nxt          # 只有预告日、且已过期：按已披露处理
        if disclosed is None:
            missing.append(row)
            continue

        reviewed = _review_evidence_date(row)
        if reviewed is None or reviewed < disclosed:
            overdue.append({
                "security_code": row.get("security_code", ""),
                "security_name": row.get("security_name", ""),
                "market_type": row.get("market_type", ""),
                "report_date": disclosed.isoformat(),
                "reviewed_at": reviewed.isoformat() if reviewed else "从未",
                "days_overdue": (as_of - disclosed).days,
            })
    return overdue, missing, upcoming


def print_overdue_report(rows: list[dict[str, str]], as_of: date) -> int:
    """打印逾期、缺日与临期清单，返回逾期只数。供每日跑批与本脚本共用。"""
    overdue, missing, upcoming = overdue_reviews(rows, as_of)
    if overdue:
        print(f"  **§6.8 复核触发① 逾期 {len(overdue)} 只**（财报已披露而带与档未按 §7.3/§7.5.5 复核）：")
        for item in sorted(overdue, key=lambda x: -int(x["days_overdue"])):
            print(f"    - {item['security_name']}（{item['market_type']}:{item['security_code']}）"
                  f"披露 {item['report_date']}，最后复核 {item['reviewed_at']}，**逾期 {item['days_overdue']} 天**")
    else:
        print("  §6.8 复核触发①：无逾期")
    if upcoming:
        names = "、".join(f"{r.get('security_name','')}（{r.get('next_report_date','')}）" for r in upcoming)
        print(f"  **今明两日财报 {len(upcoming)} 只**（披露次日须按 §7.5.5 express 复核）：{names}")
    if missing:
        names = "、".join(f"{r.get('security_name','')}" for r in missing)
        print(f"  无财报日 {len(missing)} 只（该市无免密钥日历源，须人工维护 `last_report_date`）：{names}")
    return len(overdue)


# --------------------------------------------------------------- 写回
def apply_to_watchlist(path: Path, found: dict[str, dict[str, str]], as_of: str) -> tuple[int, int]:
    rows = load_overseas(path)
    fields = list(rows[0].keys())
    for column in ("last_report_date", "next_report_date", "next_report_source"):
        if column not in fields:
            fields.append(column)

    written = skipped = 0
    for row in rows:
        for column in ("last_report_date", "next_report_date", "next_report_source"):
            row.setdefault(column, "")
        hit = match_symbol(row.get("security_code", ""), found)
        if not hit or not (hit["last"] or hit["next"]):
            skipped += 1
            continue
        if hit["last"]:
            row["last_report_date"] = hit["last"]
        if hit["next"]:
            row["next_report_date"] = hit["next"]
        row["next_report_source"] = f"nasdaq_calendar@{as_of}"
        written += 1

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return written, skipped


def write_calendar_snapshot(path: Path, rows: list[dict[str, str]], found: dict[str, dict[str, str]]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for row in rows:
        hit = match_symbol(row.get("security_code", ""), found)
        out.append({
            "security_code": row.get("security_code", ""),
            "security_name": row.get("security_name", ""),
            "market_type": row.get("market_type", ""),
            "last_report_date": (hit or {}).get("last") or row.get("last_report_date", ""),
            "next_report_date": (hit or {}).get("next") or row.get("next_report_date", ""),
            "report_time": (hit or {}).get("time", ""),
            "fiscal_quarter_ending": (hit or {}).get("fq", ""),
            "source": "nasdaq_calendar" if hit else ("manual" if row.get("last_report_date") else ""),
            "retrieved_at_utc": now,
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALENDAR_FIELDS)
        writer.writeheader()
        writer.writerows(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="海外财报日历抓取与复核逾期自检（§6.8，OI-039）")
    parser.add_argument("--as-of", required=True, help="扫描基准日 / 自检基准日 YYYY-MM-DD")
    parser.add_argument("--back-days", type=int, default=120, help="向后扫描天数（缺省 120，主判据来源）")
    parser.add_argument("--days", type=int, default=120, help="向前扫描天数（缺省 120，只作提前量提示）")
    parser.add_argument("--overseas", type=Path, default=OVERSEAS_CSV)
    parser.add_argument("--calendar-csv", type=Path, default=CALENDAR_CSV)
    parser.add_argument("--apply", action="store_true", help="把查到的美股财报日写回 §6.8 清单")
    parser.add_argument("--check-only", action="store_true", help="不抓取，只跑逾期自检")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--pause", type=float, default=0.25)
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)
    rows = load_overseas(args.overseas)

    if args.check_only:
        print(f"海外复核逾期自检（§6.8，{as_of}）：清单 {len(rows)} 家")
        return 1 if print_overdue_report(rows, as_of) else 0

    coverable = [r for r in rows if r.get("market_type") == "US" or r.get("security_code") in EARNINGS_PROXY]
    print(f"扫描 Nasdaq 财报日历：{as_of} 前 {args.back_days} 天 / 后 {args.days} 天"
          f"（清单 {len(rows)} 家，其中该源可覆盖 {len(coverable)} 家）")
    found = scan_nasdaq_calendar(as_of, args.back_days, args.days, args.timeout, args.pause)
    print(f"  窗口内共 {len(found)} 个标的有财报日")

    hits = [r for r in coverable if match_symbol(r.get("security_code", ""), found)]
    misses = [r for r in coverable if not match_symbol(r.get("security_code", ""), found)]
    print(f"  清单命中 {len(hits)}/{len(coverable)} 家"
          + (f"；**未命中**：{'、'.join(r['security_name'] + '(' + r['security_code'] + ')' for r in misses)}" if misses else ""))

    write_calendar_snapshot(args.calendar_csv, rows, found)
    print(f"  快照写入 {args.calendar_csv}")

    if args.apply:
        written, skipped = apply_to_watchlist(args.overseas, found, args.as_of)
        print(f"  写回 {args.overseas.name}：{written} 行更新 `next_report_date`，{skipped} 行保持原值（非美股或未命中）")
        rows = load_overseas(args.overseas)

    return 1 if print_overdue_report(rows, as_of) else 0


if __name__ == "__main__":
    raise SystemExit(main())

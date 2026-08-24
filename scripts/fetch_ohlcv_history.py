#!/usr/bin/env python3
"""逐票历史日线（**不复权原始价**）+ 除权除息事件，作为回测数据底座（结 OI-035）。

用户 2026-08-07 裁定
--------------------
> 池 + 持仓，拉取每个股票**上市后的所有数据**，然后请一定要明确取数据的方式，我建议采用
> **不复权原始价格 + 分红送转/配股等除权除息信息**，方便后续回测分析，计算 return。

**这个取法是对的，而且实测证明前复权在长历史上根本不能用**：腾讯 `qfq` 序列对贵州茅台
2015-01-05 返回的开盘价是 **−129.35**——累计分红在向后摊回时超过了当年的股价，前复权序列
直接变成负数。用它算收益率会得到无意义的结果，而这类失效**不会报错**，只会安静地给出错的数
（§13 第 3 条）。故本模块只存原始价，复权在**计算时**按事件重建。

产出
----
* ``data/raw/ohlcv/<代码>.csv``——不复权日线：``date,open,close,high,low,volume``（逐票一文件，增量追加）
* ``data/raw/corporate_actions/a_share_corporate_actions.csv``——全部除权除息事件：
  ``security_code,ex_dividend_date,cash_per_share,share_ratio,plan,report_date,plan_notice_date,progress``

两者分开存是有意的：**价格是观测，事件是事实**，前者天天变、后者只在除权日新增一行。
合起来才能算总收益率，任何一份单独都不够。

数据源与边界
------------
* 腾讯 `web.ifzq.gtimg.cn/appstock/app/fqkline/get`，`param=<secid>,day,<起>,<止>,<条数>,`
  末位留空即**不复权**。**单次最多返回 640 根**（实测：请求 1000 返回 640，请求 3000 返回空），
  故按日期窗分页回溯，直到某窗返回空即认为到达上市日。
* 除权除息取东财 `RPT_SHAREBONUS_DET` 的 `EX_DIVIDEND_DATE`／`PRETAX_BONUS_RMB`（每 10 股税前派息）
  ／`BONUS_RATIO`（每 10 股送股）／`IT_RATIO`（每 10 股转增）。**配股不在该表**，改取新浪
  「分红配股」页的配股表（`sharebonus_2`：每 10 股配股数／配股价／除权日／公告日），只落已有除权日的
  已实施配股，写入同一事件库的 `rights_ratio`（每股配股数）／`rights_price` 两列；两源按 (代码, 除权日, 类别) 去重。
* **幸存者偏差未解决**：universe 取自当前的池与持仓，退市与更名股票不在其中（§12.4 已登记）。
  本模块不假装解决它，只把它写在这里。

用法::

    python3 scripts/fetch_ohlcv_history.py --as-of 2026-08-07                 # 池+持仓，全历史，增量
    python3 scripts/fetch_ohlcv_history.py --as-of 2026-08-07 --limit 5       # 冒烟
    python3 scripts/fetch_ohlcv_history.py --as-of 2026-08-07 --actions-only  # 只刷除权事件
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
OHLCV_DIR = ROOT / "data/raw/ohlcv"
ACTIONS_CSV = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"

# 用 `proxy.finance.qq.com/.../**newfqkline**/get` 而不是 `web.ifzq.gtimg.cn/.../fqkline/get`：
# 后者**完全不服务北交所**（实测 bj920982／bj430047／bj873223 一律返回 0 根，且**不报错**），
# 前者对北交所与沪深都正常。首版用了后者，3 只北交所票因此拿到 0 根空文件。
# 这个 endpoint 也是 `screen_daily_volume_price_signals.fetch_daily_rows` 在用的那个——
# 生产路径早就是对的，是本脚本另挑了一个。
KLINE_API = ("https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
             "?param={secid},day,{start},{end},{count},")
EM_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}

MAX_BARS_PER_CALL = 640          # 实测上限，见模块 docstring
OHLCV_FIELDS = ["date", "open", "close", "high", "low", "volume"]
ACTION_FIELDS = ["security_code", "security_name", "ex_dividend_date",
                 "cash_per_share", "share_ratio", "plan", "report_date",
                 "plan_notice_date", "progress", "rights_ratio", "rights_price"]
SINA_RIGHTS_URL = "https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{code}.phtml"
# `plan_notice_date` = 董事会预案公告日（东财 `PLAN_NOTICE_DATE`）——股利折现的分红可得日（`divspread_dividend`）。
# **预案已公告、尚未除权的分红也落盘**（`ex_dividend_date` 为空、`progress` 记东财进度）：除权侧的
# 读者一律按「除权日为空即跳过」处理，股利折现侧则从预案公告日起计入。同一代码重取时旧的预案行整体清掉，
# 由本次取到的行（已实施则带除权日）接替，预案作废即消失。


# 北交所代码段：430/83x/87x/88x 是老三板转来的，**920 是 2023 年后新发的**。
# 首版只认 `4`/`8` 开头，把 920xxx 判成了深市 `sz920982`，腾讯对该 secid **不报错、只返回空**
# ——3 只北交所票因此拿到 0 根 K 线。这正是 §13 第 3 条点名过的同一个失效
# （「北交所 SECUCODE 后缀写成 .SZ 导致财务接口不报错只返回空」）的**第五次复发**，
# 只是这次换成了行情接口。故这里既认 `exchange` 字段也认代码段，两条都不依赖对方。
BSE_PREFIXES = ("43", "83", "87", "88", "92")


def secid(code: str, exchange: str) -> str:
    code = code.zfill(6)
    market = (exchange or "").upper()
    if market.startswith("BS") or market == "BJSE" or code[:2] in BSE_PREFIXES:
        return "bj" + code
    if market.startswith("SS") or market == "SSE":
        return "sh" + code
    if market.startswith("SZ"):
        return "sz" + code
    return ("sh" if code[0] == "6" else "sz") + code


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def fetch_window(sid: str, start: str, end: str, timeout: float) -> list[list]:
    url = KLINE_API.format(secid=sid, start=start, end=end, count=MAX_BARS_PER_CALL)
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    data = (payload.get("data") or {}).get(sid) or {}
    return data.get("day") or []


def fetch_full_history(sid: str, until: date, since: date | None, timeout: float,
                       pause: float) -> list[dict[str, str]]:
    """按日期窗向前分页，直到某窗返回空（= 到达上市日或 `since`）。

    每窗取约 2.5 年（640 根 ÷ 244 交易日/年 ≈ 2.6 年），留一点余量防边界丢根。
    窗与窗之间按 `date` 去重合并——分页边界重叠是正常的，重叠比漏根安全。
    """
    seen: dict[str, list] = {}
    end = until
    while True:
        start = end - timedelta(days=900)
        if since and start < since:
            start = since
        rows = fetch_window(sid, start.isoformat(), end.isoformat(), timeout)
        time.sleep(pause)
        if not rows:
            break
        for row in rows:
            seen.setdefault(str(row[0]), row)
        oldest = min(str(row[0]) for row in rows)
        if since and oldest <= since.isoformat():
            break
        new_end = date.fromisoformat(oldest) - timedelta(days=1)
        if new_end >= end:                      # 没有前进 = 到底了，防死循环
            break
        end = new_end

    out = []
    for key in sorted(seen):
        row = seen[key]
        out.append({
            "date": str(row[0]), "open": str(row[1]), "close": str(row[2]),
            "high": str(row[3]), "low": str(row[4]),
            "volume": str(row[5]) if len(row) > 5 else "",
        })
    return out


def fetch_actions(code: str, timeout: float) -> list[dict[str, str]]:
    query = urllib.parse.urlencode({
        "reportName": "RPT_SHAREBONUS_DET",
        "columns": ("SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,EX_DIVIDEND_DATE,PLAN_NOTICE_DATE,"
                    "PRETAX_BONUS_RMB,BONUS_RATIO,IT_RATIO,IMPL_PLAN_PROFILE,ASSIGN_PROGRESS"),
        "pageSize": "200",
        "sortColumns": "EX_DIVIDEND_DATE",
        "sortTypes": "1",
        "filter": f'(SECURITY_CODE="{code}")',
    })
    request = urllib.request.Request(f"{EM_API}?{query}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = ((payload.get("result") or {}).get("data")) or []

    out = []
    for row in rows:
        ex = (row.get("EX_DIVIDEND_DATE") or "")[:10]
        plan_notice = (row.get("PLAN_NOTICE_DATE") or "")[:10]
        cash = float(row.get("PRETAX_BONUS_RMB") or 0) / 10
        share = (float(row.get("BONUS_RATIO") or 0) + float(row.get("IT_RATIO") or 0)) / 10
        if not cash and not share:
            continue                            # 只预披露「拟分红」、无金额：既不是事件也不是分子
        if not ex and not plan_notice:
            continue
        out.append({
            "security_code": code.zfill(6),
            "security_name": row.get("SECURITY_NAME_ABBR", ""),
            "ex_dividend_date": ex,
            "cash_per_share": f"{cash:.6f}",
            "share_ratio": f"{share:.6f}",
            "plan": row.get("IMPL_PLAN_PROFILE", ""),
            "report_date": (row.get("REPORT_DATE") or "")[:10],
            "plan_notice_date": plan_notice,
            "progress": row.get("ASSIGN_PROGRESS", "") or "",
        })
    return out


def fetch_rights(code: str, timeout: float) -> list[dict[str, str]]:
    """新浪配股表 → 事件行（只取已有除权日的已实施配股）。每股配股数 = 每 10 股配股数 ÷ 10。"""
    import html as _html
    import re as _re
    request = urllib.request.Request(SINA_RIGHTS_URL.format(code=code.zfill(6)),
                                     headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("gbk", errors="ignore")
    marker = 'id="sharebonus_2"'
    if marker not in text:
        return []
    table = text[text.index(marker):]
    table = table[:table.find("</table>")] if "</table>" in table else table
    out = []
    for tr in _re.findall(r"<tr[^>]*>(.*?)</tr>", table, _re.S):
        cells = [_html.unescape(_re.sub("<[^>]+>", "", c)).strip()
                 for c in _re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, _re.S)]
        if len(cells) < 5 or not _re.match(r"\d{4}-\d{2}-\d{2}$", cells[0]):
            continue
        notice, per_ten, price, ex = cells[0], cells[1], cells[2], cells[4][:10]
        try:
            ratio = float(per_ten) / 10.0
            rights_price = float(price)
        except ValueError:
            continue
        if ratio <= 0 or not _re.match(r"\d{4}-\d{2}-\d{2}$", ex):
            continue                              # 未实施／无除权日的配股不是事件
        out.append({
            "security_code": code.zfill(6), "security_name": "",
            "ex_dividend_date": ex, "cash_per_share": "0.000000", "share_ratio": "0.000000",
            "plan": f"10配{per_ten}股@{price}元（新浪）", "report_date": "",
            "plan_notice_date": notice, "progress": "配股实施",
            "rights_ratio": f"{ratio:.6f}", "rights_price": f"{rights_price:.4f}",
        })
    return out


def action_key(action: dict[str, str]) -> tuple[str, str]:
    """除权事件按 (代码, 除权日[, rights]) 去重；预案行无除权日，按 (代码, plan:报告期:预案日) 去重。
    同日既分红又配股时两行并存（读者按列相加）。"""
    ex = action.get("ex_dividend_date") or ""
    if ex:
        if float(action.get("rights_ratio") or 0) > 0:
            return (action["security_code"], f"{ex}:rights")
        return (action["security_code"], ex)
    return (action["security_code"], f"plan:{action.get('report_date', '')}:{action.get('plan_notice_date', '')}")


# --------------------------------------------------------------- 主流程
def universe() -> list[tuple[str, str, str]]:
    rows = {r["security_code"].zfill(6): (r.get("security_name", ""), r.get("exchange", ""))
            for r in load_csv(POOL)}
    for r in load_csv(HOLDINGS):
        rows.setdefault(r["security_code"].zfill(6), (r.get("security_name", ""), ""))
    return [(code, name, exchange) for code, (name, exchange) in sorted(rows.items())]


def main() -> int:
    parser = argparse.ArgumentParser(description="逐票不复权日线 + 除权除息事件（OI-035）")
    parser.add_argument("--as-of", required=True, help="截止交易日 YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只（冒烟用）")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--pause", type=float, default=0.12)
    parser.add_argument("--actions-only", action="store_true", help="只刷除权事件，不动日线")
    parser.add_argument("--rights-only", action="store_true",
                        help="只刷新浪配股事件（不动东财分红、不动日线）；全市场首次补取用")
    parser.add_argument("--no-rights", action="store_true", help="跳过新浪配股表（只刷东财分红送转）")
    parser.add_argument("--full", action="store_true", help="忽略已有文件，重下全历史")
    parser.add_argument("--since", help="只取该日之后的日线（缺省全历史）。回测只需 2006 起时可大幅提速")
    parser.add_argument("--out-suffix", default="", help="并行分片时避免除权事件文件互相覆盖")
    parser.add_argument("--codes-file", type=Path,
                        help="改用文件里的代码清单（每行一个），用于补取**当前池外**的历史标的"
                             "——这正是解幸存者偏差所需（§12.4 登记的那一半）")
    args = parser.parse_args()

    until = date.fromisoformat(args.as_of)
    targets = universe()
    if args.codes_file:
        wanted = {line.strip().zfill(6) for line in args.codes_file.read_text().split() if line.strip()}
        known = {code: (code, name, exchange) for code, name, exchange in targets}
        # 池外代码在 a_share_securities.csv 里查交易所；查不到的按代码段兜底（见 secid）
        extra = []
        with (ROOT / "data/raw/a_share_securities.csv").open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("security_code") or row.get("\ufeffsecurity_code") or "").zfill(6)
                if code in wanted and code not in known:
                    extra.append((code, row.get("security_name", ""), row.get("exchange", "")))
        found = {e[0] for e in extra} | (wanted & set(known))
        missing = sorted(wanted - found)
        # **查无的这批恰恰是最要紧的**：证券主表是「当前」的，退市股本就不在其中，
        # 而它们正是幸存者偏差里「消失的那一半」。故仍按代码段兜底尝试取数
        # （`secid()` 对空 exchange 会按首位判沪深），取不到再算失败。
        extra += [(c, "", "") for c in missing]
        targets = [known[c] for c in sorted(wanted) if c in known] + extra
        print(f"按清单取数：请求 {len(wanted)} 只｜命中 {len(targets)} 只"
              + (f"｜证券主表查无 {len(missing)} 只（多为已退市）→ **仍按代码段兜底尝试**" if missing else ""))
    if args.limit:
        targets = targets[:args.limit]
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    ACTIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    print(f"universe {len(targets)} 只（池 + 持仓）｜截止 {until}｜不复权原始价 + 除权事件")

    # 并行分片时各写各的除权文件，跑完再合并——否则 6 个进程会互相覆盖对方已抓到的事件
    actions_path = (ACTIONS_CSV.with_name(ACTIONS_CSV.stem + args.out_suffix + ACTIONS_CSV.suffix)
                    if args.out_suffix else ACTIONS_CSV)

    def flush_actions(actions: list[dict[str, str]]) -> int:
        """把除权事件并进磁盘文件并返回总行数。

        **必须增量落盘**：首版只在跑完时写一次，结果 2026-08-07 首轮跑到 177/261 被中断，
        已抓到的除权事件**全部丢失**（文件里只剩冒烟测试那 3 只的 73 行），而日线因为是逐票
        写盘所以一根没丢。同一次运行里两种写法、两种结局，正是 §13 第 3 条那类「丢了数据
        不报警」的成因——故这里改为每批落盘。
        """
        refetched = {a["security_code"] for a in actions if float(a.get("rights_ratio") or 0) <= 0}
        merged = {action_key(a): a for a in load_csv(actions_path)
                  if a.get("security_code")
                  # 本批重取到分红的代码：旧预案行整体清掉，由本次取到的行接替（已实施→带除权日；作废→消失）
                  and not (a["security_code"] in refetched and not (a.get("ex_dividend_date") or ""))}
        merged.update({action_key(a): a for a in actions})
        with actions_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=ACTION_FIELDS)
            writer.writeheader()
            writer.writerows([merged[k] for k in sorted(merged)])
        return len(merged)

    all_actions: list[dict[str, str]] = []
    bar_counts, failed, skipped = [], [], 0
    for index, (code, name, exchange) in enumerate(targets, 1):
        path = OHLCV_DIR / f"{code}.csv"
        existing = load_csv(path) if not args.full else []
        since = date.fromisoformat(args.since) if args.since else None
        if existing:
            last = max(row["date"] for row in existing)
            if last >= args.as_of:
                skipped += 1
            since = date.fromisoformat(last) + timedelta(days=1)

        if not args.rights_only:
            try:
                actions = fetch_actions(code, args.timeout)
                all_actions.extend(actions)
                time.sleep(args.pause)
            except Exception as exc:                           # noqa: BLE001
                failed.append(f"{code} 除权({type(exc).__name__})")
        if not args.no_rights:
            try:
                rights = fetch_rights(code, args.timeout)
                for r in rights:
                    r["security_name"] = name
                all_actions.extend(rights)
                time.sleep(args.pause)
            except Exception as exc:                           # noqa: BLE001
                failed.append(f"{code} 配股({type(exc).__name__})")
        if args.rights_only and index % 200 == 0:
            print(f"  [{index}/{len(targets)}] 配股已取至 {name}({code})，累计事件 {len(all_actions)}", flush=True)

        if len(all_actions) >= 200:                            # 每约 10-20 只落一次盘
            flush_actions(all_actions)
            all_actions = []

        if args.actions_only or args.rights_only:
            continue
        if existing and since and since > until:
            bar_counts.append(len(existing))
            continue
        try:
            fresh = fetch_full_history(secid(code, exchange), until, since, args.timeout, args.pause)
        except Exception as exc:                               # noqa: BLE001
            failed.append(f"{code} 日线({type(exc).__name__})")
            continue

        merged = {row["date"]: row for row in existing}
        merged.update({row["date"]: row for row in fresh})
        rows = [merged[key] for key in sorted(merged)]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OHLCV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        bar_counts.append(len(rows))
        if index % 25 == 0 or index == len(targets):
            print(f"  [{index}/{len(targets)}] {name}({code}) 累计 {len(rows)} 根")

    total_actions = flush_actions(all_actions)
    final_rows = load_csv(ACTIONS_CSV)
    covered = len({a["security_code"] for a in final_rows if a.get("security_code")})
    n_rights = sum(1 for a in final_rows if float(a.get("rights_ratio") or 0) > 0)
    print(f"除权除息事件 {total_actions} 行（含配股 {n_rights} 行）、覆盖 {covered}/{len(targets)} 只 → {ACTIONS_CSV.relative_to(ROOT)}")

    # §13 第 3 条硬自检：新增数据源必须核对非空行数与覆盖面。
    if bar_counts:
        print(f"日线覆盖 {len(bar_counts)}/{len(targets)} 只｜合计 {sum(bar_counts):,} 根"
              f"｜单票中位 {sorted(bar_counts)[len(bar_counts) // 2]:,} 根"
              f"｜最短 {min(bar_counts):,}｜最长 {max(bar_counts):,}")

    # **零根必须显式告警**：首轮 3 只北交所票拿到 0 根而整批报告「覆盖 261/261」，
    # 因为覆盖数只数了文件个数、没数内容——「有文件」与「有数据」被当成了一回事。
    empty = [(code, name) for code, name, _ in targets
             if (OHLCV_DIR / f"{code}.csv").exists()
             and sum(1 for _ in (OHLCV_DIR / f"{code}.csv").open(encoding="utf-8")) <= 1]
    if empty:
        print(f"  **零根 {len(empty)} 只（有文件但无数据，按失败处理）**："
              + "、".join(f"{name}({code})" for code, name in empty))
    if skipped:
        print(f"  已是最新、未重取 {skipped} 只")
    if failed:
        print(f"  **失败 {len(failed)} 项**：{'、'.join(failed[:10])}" + ("…" if len(failed) > 10 else ""))
    print("  ⚠ 已知缺口：①配股不在 RPT_SHAREBONUS_DET，受影响票须人工补；"
          "②universe 取自当前池与持仓，**退市/更名股票不在其中（幸存者偏差，§12.4）**")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
